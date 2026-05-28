"""
Tool for the Director agent to update reference descriptions.
This allows the agent to independently determine and describe how it intends to use each reference.
"""

import httpx
from typing import Optional
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Reference Descriptions")


@mcp.tool()
async def update_reference_description(
    reference_id: str,
    description: str,
) -> str:
    """
    Update the description of a reference to indicate how the agent intends to use it.
    
    Use this tool when you determine how a reference should be used in the production.
    For example:
    - "lead actor" for the main character reference
    - "commercial product" for a product shot reference
    - "villain character" for antagonist references
    - "background environment" for location references
    - "prop to reuse" for objects that should appear in multiple scenes
    
    Args:
        reference_id: The ID of the reference to update
        description: A clear description of how this reference will be used (e.g., "lead actor", "commercial product")
    
    Returns:
        Confirmation message
    """
    try:
        # Get the director run ID from environment or context
        # For now, we'll need to pass it through the tool call
        # This is a simplified version - the actual implementation would need the run ID
        return f"Reference {reference_id} description would be updated to: {description}"
    except Exception as e:
        return f"Failed to update reference description: {str(e)}"


@mcp.tool()
async def update_reference_description_with_run(
    reference_id: str,
    description: str,
    director_run_id: str,
) -> str:
    """
    Update the description of a reference to indicate how the agent intends to use it.
    
    Use this tool when you determine how a reference should be used in the production.
    For example:
    - "lead actor" for the main character reference
    - "commercial product" for a product shot reference
    - "villain character" for antagonist references
    - "background environment" for location references
    - "prop to reuse" for objects that should appear in multiple scenes
    
    Args:
        reference_id: The ID of the reference to update
        description: A clear description of how this reference will be used (e.g., "lead actor", "commercial product")
        director_run_id: The ID of the Director run
    
    Returns:
        Confirmation message
    """
    try:
        # Call the API endpoint to update the reference description
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"http://localhost:3000/api/director/{director_run_id}/update-reference-description",
                json={
                    "referenceId": reference_id,
                    "description": description,
                },
                timeout=10.0,
            )
            
            if response.status_code == 200:
                return f"Reference {reference_id} description updated to: {description}"
            else:
                return f"Failed to update reference description: {response.status_code}"
    except Exception as e:
        return f"Failed to update reference description: {str(e)}"


def register(mcp_instance: FastMCP) -> None:
    """Register reference description tools with the MCP instance."""
    mcp_instance.add_tool(update_reference_description)
    mcp_instance.add_tool(update_reference_description_with_run)


