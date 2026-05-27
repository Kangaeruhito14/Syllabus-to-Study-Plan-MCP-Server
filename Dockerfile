FROM python:3.12-slim

WORKDIR /app

# System deps: Tesseract (OCR for scanned PDFs) + Poppler (pdf2image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir -e "."

# Default: stdio (for MCPize / mcp-proxy). Override with TRANSPORT=streamable-http for self-hosted HTTP.
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["syllabus-mcp"]
