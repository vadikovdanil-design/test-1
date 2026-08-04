import os
import sys
import uvicorn

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("==================================================")
    print("  SAG for people - HR CRM Portal Server Starting")
    print("  Access UI at: http://127.0.0.1:8000 or http://10.110.57.147:8000")
    print("==================================================")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

