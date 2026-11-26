"""Entry point alternatif untuk menjalankan aplikasi FastAPI.

Sprint 9: file ini sengaja hanya membungkus ``app.main:app``. Sebelumnya file
ini mendefinisikan aplikasi kedua dengan lifespan yang TIDAK menjalankan
migrasi aditif maupun recovery, sehingga `uvicorn main:app` diam-diam
melewati dua langkah penting tersebut. Sekarang semua cara menjalankan aplikasi
memakai satu aplikasi dan satu lifespan yang sama.

Jalankan dengan salah satu cara:

    python main.py
    uvicorn app.main:app --reload --port 8000
    uvicorn main:app --reload --port 8000
"""

import os
import sys

_BACKEND_ROOT = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402  (satu-satunya aplikasi; lifespan lengkap)

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=settings.BACKEND_PORT,
        reload=settings.DEBUG,
    )
