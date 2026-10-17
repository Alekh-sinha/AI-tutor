def main() -> None:
    import uvicorn

    uvicorn.run("ai_teacher_api.app:app", host="127.0.0.1", port=8000, reload=True)
