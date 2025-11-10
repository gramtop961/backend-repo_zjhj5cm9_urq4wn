"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- Idea -> "idea" collection
- Comment -> "comment" collection
- Vote -> "vote" collection
"""

from pydantic import BaseModel, Field
from typing import Optional, List

class Idea(BaseModel):
    """
    Ideas posted by users
    Collection name: "idea"
    """
    title: str = Field(..., description="Idea title")
    description: str = Field(..., description="Short description of the idea")
    author: Optional[str] = Field(None, description="Name of the person posting the idea")
    link: Optional[str] = Field(None, description="Optional external link or prototype")
    tags: List[str] = Field(default_factory=list, description="List of tags for filtering")

class Comment(BaseModel):
    """
    Comments on ideas
    Collection name: "comment"
    """
    idea_id: str = Field(..., description="ID of the idea being commented on")
    author: Optional[str] = Field(None, description="Name of the commenter")
    content: str = Field(..., description="Comment text")

class Vote(BaseModel):
    """
    Upvotes for ideas
    Collection name: "vote"
    """
    idea_id: str = Field(..., description="ID of the idea being upvoted")
    voter: Optional[str] = Field(None, description="Optional name or identifier of voter")
