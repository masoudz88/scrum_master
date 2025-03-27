import os
import sys
import traceback
from typing import Any, List, Dict, Optional
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from jira import JIRA

class JiraScrum:
    def __init__(self):
        # Load environment variables
        load_dotenv()
        
        # Initialize MCP Server
        self.mcp = FastMCP("scrum")
        print("MCP Server initialized", file=sys.stderr)
        
        # Initialize Jira client
        self._init_jira()
        
        # Register MCP tools
        self._register_tools()
    
    def _init_jira(self):
        """Initialize the Jira client with API credentials."""
        try:
            self.jira_url = os.getenv("JIRA_URL")
            self.jira_username = os.getenv("JIRA_USERNAME")
            self.jira_api_token = os.getenv("JIRA_API_TOKEN")
            
            if not self.jira_url or not self.jira_username or not self.jira_api_token:
                raise ValueError("Missing Jira credentials in environment variables")
            
            self.jira = JIRA(
                server=self.jira_url,
                basic_auth=(self.jira_username, self.jira_api_token)
            )
            print(f"Jira client initialized successfully", file=sys.stderr)
            print(f"Connected to Jira instance: {self.jira_url}", file=sys.stderr)
        except Exception as e:
            print(f"Error initializing Jira client: {str(e)}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)
    
    def _register_tools(self):
        """Register MCP tools for Jira Scrum Master operations."""
        
        @self.mcp.tool()
        async def get_sprint_details(board_id: int, sprint_state: str = "active") -> Dict[str, Any]:
            """
            Get details about sprints for a specific board.
            
            Args:
                board_id: The ID of the Jira board
                sprint_state: State of sprints to fetch (active, future, closed)
                
            Returns:
                Dictionary with sprint details
            """
            print(f"Fetching {sprint_state} sprints for board #{board_id}", file=sys.stderr)
            try:
                sprints = self.jira.sprints(board_id, sprint_state)
                sprint_details = []
                
                for sprint in sprints:
                    sprint_info = {
                        "id": sprint.id,
                        "name": sprint.name,
                        "state": sprint.state,
                        "start_date": getattr(sprint, "startDate", None),
                        "end_date": getattr(sprint, "endDate", None),
                        "goal": getattr(sprint, "goal", "")
                    }
                    
                    # Get issues in this sprint
                    jql = f"sprint = {sprint.id} ORDER BY status"
                    issues = self.jira.search_issues(jql)
                    sprint_info["issues"] = [
                        {
                            "key": issue.key,
                            "summary": issue.fields.summary,
                            "status": issue.fields.status.name,
                            "assignee": getattr(issue.fields.assignee, "displayName", "Unassigned"),
                            "story_points": getattr(issue.fields, "customfield_10002", 0)  # Assuming story points field
                        }
                        for issue in issues
                    ]
                    
                    # Calculate sprint metrics
                    total_story_points = sum(issue.get("story_points", 0) or 0 for issue in sprint_info["issues"])
                    completed_points = sum((issue.get("story_points", 0) or 0) for issue in sprint_info["issues"] 
                                         if issue["status"] in ["Done", "Closed", "Completed"])
                    
                    sprint_info["metrics"] = {
                        "total_issues": len(sprint_info["issues"]),
                        "total_story_points": total_story_points,
                        "completed_story_points": completed_points,
                        "completion_percentage": (completed_points / total_story_points * 100) if total_story_points > 0 else 0
                    }
                    
                    sprint_details.append(sprint_info)
                
                print(f"Successfully fetched {len(sprint_details)} sprints", file=sys.stderr)
                return {"sprints": sprint_details}
                
            except Exception as e:
                print(f"Error fetching sprint details: {str(e)}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return {"error": str(e)}
        
        @self.mcp.tool()
        async def get_issue_details(issue_key: str) -> Dict[str, Any]:
            """
            Get detailed information about a Jira issue.
            
            Args:
                issue_key: The Jira issue key (e.g., 'PROJ-123')
                
            Returns:
                Dictionary with issue details
            """
            print(f"Fetching details for issue {issue_key}", file=sys.stderr)
            try:
                issue = self.jira.issue(issue_key)
                
                # Get comments
                comments = [
                    {
                        "author": comment.author.displayName,
                        "body": comment.body,
                        "created": comment.created
                    }
                    for comment in issue.fields.comment.comments
                ]
                
                # Get issue history
                changelog = self.jira.issue(issue_key, expand='changelog').changelog
                history = [
                    {
                        "author": history.author.displayName,
                        "created": history.created,
                        "items": [
                            {
                                "field": item.field,
                                "from_value": item.fromString,
                                "to_value": item.toString
                            }
                            for item in history.items
                        ]
                    }
                    for history in changelog.histories
                ]
                
                issue_details = {
                    "key": issue.key,
                    "summary": issue.fields.summary,
                    "description": issue.fields.description,
                    "status": issue.fields.status.name,
                    "assignee": getattr(issue.fields.assignee, "displayName", "Unassigned"),
                    "reporter": issue.fields.reporter.displayName,
                    "created": issue.fields.created,
                    "updated": issue.fields.updated,
                    "priority": issue.fields.priority.name,
                    "issue_type": issue.fields.issuetype.name,
                    "story_points": getattr(issue.fields, "customfield_10002", None),  # Assuming story points field
                    "sprint": getattr(issue.fields, "customfield_10001", None),  # Assuming sprint field
                    "components": [c.name for c in issue.fields.components],
                    "labels": issue.fields.labels,
                    "comments": comments,
                    "history": history
                }
                
                print(f"Successfully fetched details for {issue_key}", file=sys.stderr)
                return issue_details
                
            except Exception as e:
                print(f"Error fetching issue details: {str(e)}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return {"error": str(e)}
        
        @self.mcp.tool()
        async def create_issue(
            project_key: str,
            issue_type: str,
            summary: str,
            description: str,
            assignee: Optional[str] = None,
            priority: Optional[str] = None,
            labels: Optional[List[str]] = None,
            story_points: Optional[float] = None
        ) -> Dict[str, Any]:
            """
            Create a new Jira issue.
            
            Args:
                project_key: The project key (e.g., 'PROJ')
                issue_type: The issue type (e.g., 'Story', 'Bug', 'Task')
                summary: Issue summary/title
                description: Detailed description of the issue
                assignee: Username of the assignee (optional)
                priority: Priority level (optional)
                labels: List of labels to add (optional)
                story_points: Number of story points (optional)
                
            Returns:
                Dictionary with created issue details
            """
            print(f"Creating new {issue_type} in project {project_key}", file=sys.stderr)
            try:
                issue_dict = {
                    "project": {"key": project_key},
                    "issuetype": {"name": issue_type},
                    "summary": summary,
                    "description": description
                }
                
                if assignee:
                    issue_dict["assignee"] = {"name": assignee}
                    
                if priority:
                    issue_dict["priority"] = {"name": priority}
                    
                if labels:
                    issue_dict["labels"] = labels
                    
                if story_points:
                    issue_dict["customfield_10002"] = story_points  # Assuming story points field
                
                new_issue = self.jira.create_issue(fields=issue_dict)
                
                print(f"Successfully created issue {new_issue.key}", file=sys.stderr)
                return {
                    "key": new_issue.key,
                    "self": new_issue.self,
                    "summary": summary,
                    "message": f"Successfully created issue {new_issue.key}"
                }
                
            except Exception as e:
                print(f"Error creating issue: {str(e)}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return {"error": str(e)}
        
        @self.mcp.tool()
        async def update_issue_status(issue_key: str, transition_to: str) -> Dict[str, Any]:
            """
            Update the status of a Jira issue.
            
            Args:
                issue_key: The Jira issue key (e.g., 'PROJ-123')
                transition_to: The status to transition to (e.g., 'In Progress', 'Done')
                
            Returns:
                Dictionary with update status
            """
            print(f"Updating status of {issue_key} to '{transition_to}'", file=sys.stderr)
            try:
                # Get available transitions
                transitions = self.jira.transitions(issue_key)
                
                # Find the transition ID that matches the requested status
                transition_id = None
                for t in transitions:
                    if t['name'].lower() == transition_to.lower():
                        transition_id = t['id']
                        break
                
                if not transition_id:
                    available_transitions = [t['name'] for t in transitions]
                    return {
                        "success": False,
                        "message": f"Cannot transition to '{transition_to}'. Available transitions: {', '.join(available_transitions)}"
                    }
                
                # Execute the transition
                self.jira.transition_issue(issue_key, transition_id)
                
                print(f"Successfully updated {issue_key} status to {transition_to}", file=sys.stderr)
                return {
                    "success": True,
                    "key": issue_key,
                    "new_status": transition_to,
                    "message": f"Successfully updated {issue_key} status to {transition_to}"
                }
                
            except Exception as e:
                print(f"Error updating issue status: {str(e)}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return {"error": str(e)}
        
        @self.mcp.tool()
        async def assign_issue(issue_key: str, assignee: str) -> Dict[str, Any]:
            """
            Assign a Jira issue to a user.
            
            Args:
                issue_key: The Jira issue key (e.g., 'PROJ-123')
                assignee: Username of the assignee
                
            Returns:
                Dictionary with assignment status
            """
            print(f"Assigning {issue_key} to {assignee}", file=sys.stderr)
            try:
                self.jira.assign_issue(issue_key, assignee)
                
                print(f"Successfully assigned {issue_key} to {assignee}", file=sys.stderr)
                return {
                    "success": True,
                    "key": issue_key,
                    "assignee": assignee,
                    "message": f"Successfully assigned {issue_key} to {assignee}"
                }
                
            except Exception as e:
                print(f"Error assigning issue: {str(e)}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return {"error": str(e)}
        
        @self.mcp.tool()
        async def add_issue_to_sprint(issue_key: str, sprint_id: int) -> Dict[str, Any]:
            """
            Add a Jira issue to a sprint.
            
            Args:
                issue_key: The Jira issue key (e.g., 'PROJ-123')
                sprint_id: The ID of the sprint
                
            Returns:
                Dictionary with update status
            """
            print(f"Adding {issue_key} to sprint {sprint_id}", file=sys.stderr)
            try:
                self.jira.add_issues_to_sprint(sprint_id, [issue_key])
                
                print(f"Successfully added {issue_key} to sprint {sprint_id}", file=sys.stderr)
                return {
                    "success": True,
                    "key": issue_key,
                    "sprint_id": sprint_id,
                    "message": f"Successfully added {issue_key} to sprint {sprint_id}"
                }
                
            except Exception as e:
                print(f"Error adding issue to sprint: {str(e)}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return {"error": str(e)}
        
        @self.mcp.tool()
        async def get_project_backlog(project_key: str, max_results: int = 50) -> Dict[str, Any]:
            """
            Get the backlog items for a project.
            
            Args:
                project_key: The project key (e.g., 'PROJ')
                max_results: Maximum number of results to return
                
            Returns:
                Dictionary with backlog items
            """
            print(f"Fetching backlog for project {project_key}", file=sys.stderr)
            try:
                # JQL query to get backlog items
                jql = f"project = {project_key} AND sprint is EMPTY ORDER BY Rank ASC"
                backlog_issues = self.jira.search_issues(jql, maxResults=max_results)
                
                backlog_items = [
                    {
                        "key": issue.key,
                        "summary": issue.fields.summary,
                        "issue_type": issue.fields.issuetype.name,
                        "priority": issue.fields.priority.name,
                        "status": issue.fields.status.name,
                        "assignee": getattr(issue.fields.assignee, "displayName", "Unassigned"),
                        "story_points": getattr(issue.fields, "customfield_10002", 0)  # Assuming story points field
                    }
                    for issue in backlog_issues
                ]
                
                print(f"Successfully fetched {len(backlog_items)} backlog items", file=sys.stderr)
                return {
                    "project": project_key,
                    "backlog_count": len(backlog_items),
                    "backlog_items": backlog_items
                }
                
            except Exception as e:
                print(f"Error fetching project backlog: {str(e)}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return {"error": str(e)}
        
        @self.mcp.tool()
        async def create_sprint(board_id: int, name: str, start_date: str, end_date: str, goal: str = "") -> Dict[str, Any]:
            """
            Create a new sprint.
            
            Args:
                board_id: The ID of the Jira board
                name: Name of the sprint
                start_date: Start date in format 'YYYY-MM-DD'
                end_date: End date in format 'YYYY-MM-DD'
                goal: Sprint goal (optional)
                
            Returns:
                Dictionary with created sprint details
            """
            print(f"Creating new sprint '{name}' for board {board_id}", file=sys.stderr)
            try:
                new_sprint = self.jira.create_sprint(
                    name=name,
                    board_id=board_id,
                    startDate=f"{start_date}T00:00:00.000Z",
                    endDate=f"{end_date}T23:59:59.000Z",
                    goal=goal
                )
                
                print(f"Successfully created sprint {new_sprint.id}: {name}", file=sys.stderr)
                return {
                    "id": new_sprint.id,
                    "name": new_sprint.name,
                    "state": getattr(new_sprint, "state", "future"),
                    "start_date": getattr(new_sprint, "startDate", start_date),
                    "end_date": getattr(new_sprint, "endDate", end_date),
                    "goal": getattr(new_sprint, "goal", goal),
                    "message": f"Successfully created sprint: {name}"
                }
                
            except Exception as e:
                print(f"Error creating sprint: {str(e)}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return {"error": str(e)}
        
        @self.mcp.tool()
        async def generate_sprint_report(board_id: int, sprint_id: int) -> Dict[str, Any]:
            """
            Generate a report for a completed sprint.
            
            Args:
                board_id: The ID of the Jira board
                sprint_id: The ID of the sprint
                
            Returns:
                Dictionary with sprint report data
            """
            print(f"Generating report for sprint {sprint_id}", file=sys.stderr)
            try:
                # Get sprint info
                sprint = self.jira.sprint(sprint_id)
                
                # Get sprint report data
                sprint_report = self.jira.sprint_report(board_id, sprint_id)
                
                # Get all issues in the sprint
                jql = f"sprint = {sprint_id}"
                sprint_issues = self.jira.search_issues(jql, maxResults=200)
                
                # Calculate various metrics
                total_issues = len(sprint_issues)
                completed_issues = sum(1 for issue in sprint_issues if issue.fields.status.name in ["Done", "Closed", "Completed"])
                
                # Story points metrics (assuming customfield_10002 is story points)
                total_story_points = sum(getattr(issue.fields, "customfield_10002", 0) or 0 for issue in sprint_issues)
                completed_points = sum((getattr(issue.fields, "customfield_10002", 0) or 0) for issue in sprint_issues 
                                    if issue.fields.status.name in ["Done", "Closed", "Completed"])
                
                # Group by issue type
                issue_types = {}
                for issue in sprint_issues:
                    issue_type = issue.fields.issuetype.name
                    if issue_type not in issue_types:
                        issue_types[issue_type] = {"total": 0, "completed": 0}
                    
                    issue_types[issue_type]["total"] += 1
                    if issue.fields.status.name in ["Done", "Closed", "Completed"]:
                        issue_types[issue_type]["completed"] += 1
                
                report = {
                    "sprint_name": sprint.name,
                    "sprint_goal": getattr(sprint, "goal", ""),
                    "start_date": getattr(sprint, "startDate", ""),
                    "end_date": getattr(sprint, "endDate", ""),
                    "state": getattr(sprint, "state", ""),
                    "metrics": {
                        "total_issues": total_issues,
                        "completed_issues": completed_issues,
                        "completion_percentage": (completed_issues / total_issues * 100) if total_issues > 0 else 0,
                        "total_story_points": total_story_points,
                        "completed_story_points": completed_points,
                        "story_point_completion": (completed_points / total_story_points * 100) if total_story_points > 0 else 0,
                        "issue_types": issue_types
                    }
                }
                
                print(f"Successfully generated report for sprint {sprint.name}", file=sys.stderr)
                return report
                
            except Exception as e:
                print(f"Error generating sprint report: {str(e)}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return {"error": str(e)}
    
    def run(self):
        """Start the MCP server."""
        try:
            print("Running MCP Server for Jira Scrum Master on 127.0.0.1:5000", file=sys.stderr)
            self.mcp.run(transport="stdio")
        except Exception as e:
            print(f"Fatal Error in MCP Server: {str(e)}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    scrum_master = JiraScrum()
    scrum_master.run()