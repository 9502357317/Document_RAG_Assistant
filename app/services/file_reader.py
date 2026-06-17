import fitz


import os
import tempfile
from fastapi import HTTPException, UploadFile

def read_pdf(file_path: str) -> str:
    text = ""

    doc = fitz.open(file_path)

    for page in doc:
        text += page.get_text()

    doc.close()

    return text


def read_txt(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()

def read_file(file_path):
    extension = file_path.split(".")[-1].lower()

    if extension == "pdf":
        return read_pdf(file_path)

    elif extension in ["txt", "md"]:
        return read_txt(file_path)

    else:
        raise ValueError("Unsupported file type")


class FileParser:
    @staticmethod
    def read_file(file: UploadFile) -> str:
        filename = file.filename or ""
        _, ext = os.path.splitext(filename.lower())
        
        if ext not in [".pdf", ".txt", ".md"]:
            raise HTTPException(
                status_code=400,
                detail="Only PDF, TXT and MD files are allowed."
            )
        
        temp_fd, temp_path = tempfile.mkstemp(suffix=ext)
        try:
            file.file.seek(0)
            content = file.file.read()
            with os.fdopen(temp_fd, "wb") as temp_file:
                temp_file.write(content)
            
            return read_file(temp_path)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail="This PDF is damaged or cannot be read. Please try another file."
            )
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass