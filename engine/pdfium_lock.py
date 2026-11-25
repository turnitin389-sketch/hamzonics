"""PDFium (pypdfium2, also used by pdfplumber to render pages) is NOT thread-safe: two
threads using it at once crash the whole process (seen with 3 checks in parallel,
Windows error 0xc000001d). Every PDFium call in this code base holds this lock."""

import threading

PDFIUM_LOCK = threading.RLock()
