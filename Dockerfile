FROM python:3.12-slim

WORKDIR /app

# System deps: Tesseract (OCR for scanned PDFs) + Poppler (pdf2image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir -e "."

# Transport: "streamable-http" (modern MCP) or "sse" (legacy)
ENV TRANSPORT=streamable-http
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["syllabus-mcp"]
