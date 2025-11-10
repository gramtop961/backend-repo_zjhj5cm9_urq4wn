import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------- Pydantic models for requests ---------
class IdeaCreate(BaseModel):
    title: str
    description: str
    author: Optional[str] = None
    link: Optional[str] = None
    tags: List[str] = []

class CommentCreate(BaseModel):
    idea_id: str
    author: Optional[str] = None
    content: str

class VoteCreate(BaseModel):
    idea_id: str
    voter: Optional[str] = None

# --------- Utility ---------

def serialize_doc(doc):
    doc["id"] = str(doc.get("_id"))
    doc.pop("_id", None)
    # convert datetimes to isoformat
    for k in ["created_at", "updated_at"]:
        if k in doc and isinstance(doc[k], datetime):
            doc[k] = doc[k].isoformat()
    return doc

# --------- Seed data on first run ---------

def ensure_seed_data():
    # If there are ideas already, skip
    count = db["idea"].count_documents({})
    if count > 0:
        return
    # Seed three ideas
    ideas = [
        {
            "title": "AI-Powered Code Reviewer",
            "description": "An agent that reviews PRs and suggests fixes.",
            "author": "Alex",
            "tags": ["AI", "DevTools"],
            "link": "https://example.com/code-reviewer"
        },
        {
            "title": "Fitness Buddy Chat",
            "description": "A chat app with a fitness coach agent.",
            "author": "Sam",
            "tags": ["Health", "Chatbot"],
            "link": "https://example.com/fitness-buddy"
        },
        {
            "title": "Travel Plan Optimizer",
            "description": "Smart itinerary planning using constraints.",
            "author": "Jamie",
            "tags": ["Travel", "Planner"],
            "link": "https://example.com/travel-optimizer"
        },
    ]
    inserted_ids = []
    for idea in ideas:
        inserted_ids.append(create_document("idea", idea))
    # Add comments and votes
    if inserted_ids:
        # comments
        create_document("comment", {"idea_id": inserted_ids[0], "author": "Maya", "content": "Love this!"})
        create_document("comment", {"idea_id": inserted_ids[0], "author": "Ravi", "content": "Would use at work."})
        create_document("comment", {"idea_id": inserted_ids[1], "author": "Chris", "content": "Nice concept."})
        # votes
        for i in range(5):
            create_document("vote", {"idea_id": inserted_ids[0], "voter": f"user_{i}"})
        for i in range(3):
            create_document("vote", {"idea_id": inserted_ids[1], "voter": f"user_{i}"})
        for i in range(8):
            create_document("vote", {"idea_id": inserted_ids[2], "voter": f"user_{i}"})

# --------- Startup ---------

@app.on_event("startup")
def startup_event():
    ensure_seed_data()
    # Enforce uniqueness: one vote per voter per idea
    try:
        db["vote"].create_index([("idea_id", 1), ("voter", 1)], unique=True)
    except Exception:
        pass

@app.get("/")
def root():
    return {"message": "Vibe Ideas API"}

# --------- Query helpers ---------

def get_time_filter(period: str):
    now = datetime.now(timezone.utc)
    if period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        return {}
    return {"created_at": {"$gte": start}}

# --------- API endpoints ---------

@app.get("/api/ideas")
def list_ideas(period: Optional[str] = None, sort: str = "votes"):
    # Fetch ideas
    ideas = get_documents("idea")
    # For each idea, compute vote and comment counts considering time filter when applicable
    time_filter = get_time_filter(period) if period in ("week", "month") else {}
    enriched = []
    for idea in ideas:
        idea_id = str(idea["_id"]) if "_id" in idea else idea.get("id")
        # Votes
        vote_filter = {"idea_id": idea_id}
        if time_filter:
            vote_filter.update(time_filter)
        votes = db["vote"].count_documents(vote_filter)
        # Comments
        comment_filter = {"idea_id": idea_id}
        if time_filter:
            comment_filter.update(time_filter)
        comments = db["comment"].count_documents(comment_filter)
        doc = serialize_doc(idea)
        doc["votes"] = votes
        doc["comments"] = comments
        enriched.append(doc)
    # Sort
    if sort == "comments":
        enriched.sort(key=lambda x: x.get("comments", 0), reverse=True)
    else:
        enriched.sort(key=lambda x: x.get("votes", 0), reverse=True)
    return enriched

@app.get("/api/ideas/{idea_id}")
def get_idea(idea_id: str):
    doc = db["idea"].find_one({"_id": ObjectId(idea_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Idea not found")
    # Include comments
    comments = list(db["comment"].find({"idea_id": idea_id}).sort("created_at", -1))
    comments = [serialize_doc(c) for c in comments]
    votes = db["vote"].count_documents({"idea_id": idea_id})
    idea = serialize_doc(doc)
    idea["comments_list"] = comments
    idea["votes"] = votes
    return idea

@app.post("/api/ideas")
def create_idea(payload: IdeaCreate):
    data = payload.model_dump()
    # Normalize link if provided (prepend https:// if missing scheme)
    link = data.get("link")
    if link:
        if not (link.startswith("http://") or link.startswith("https://")):
            data["link"] = f"https://{link}"
    new_id = create_document("idea", data)
    doc = db["idea"].find_one({"_id": ObjectId(new_id)})
    return serialize_doc(doc)

@app.post("/api/comments")
def add_comment(payload: CommentCreate):
    # Validate idea exists
    if not db["idea"].find_one({"_id": ObjectId(payload.idea_id)}):
        raise HTTPException(status_code=404, detail="Idea not found")
    _id = create_document("comment", payload)
    doc = db["comment"].find_one({"_id": ObjectId(_id)})
    return serialize_doc(doc)

@app.post("/api/votes")
def add_vote(payload: VoteCreate, request: Request):
    # Validate idea exists
    if not db["idea"].find_one({"_id": ObjectId(payload.idea_id)}):
        raise HTTPException(status_code=404, detail="Idea not found")
    # Determine voter identity (prefer provided voter, fall back to client IP)
    voter_identity = payload.voter or (request.client.host if request.client else None)
    if not voter_identity:
        # If no voter identity can be determined, reject to prevent duplicate votes
        raise HTTPException(status_code=400, detail="Missing voter identity")
    # Enforce one vote per voter per idea
    existing = db["vote"].find_one({"idea_id": payload.idea_id, "voter": voter_identity})
    if existing:
        raise HTTPException(status_code=409, detail="Already voted")
    _id = create_document("vote", {"idea_id": payload.idea_id, "voter": voter_identity})
    doc = db["vote"].find_one({"_id": ObjectId(_id)})
    return serialize_doc(doc)

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    import os
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
