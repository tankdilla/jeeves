# main.py
from fastapi import FastAPI
from routers import influencers, campaigns, threads, messages

app = FastAPI(title="Jeeves Influencer Outreach MVP")

app.include_router(influencers.router, prefix="/influencers", tags=["influencers"])
app.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
app.include_router(threads.router, prefix="/threads", tags=["threads"])
app.include_router(messages.router, prefix="/messages", tags=["messages"])

@app.get("/health")
def health():
    return {"ok": True}
