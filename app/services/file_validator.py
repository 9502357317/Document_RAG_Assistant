from fastapi import HTTPException, UploadFile
import os

class FileValidator:
    @staticmethod
    def validate_file_type(file: UploadFile) -> None:
        """
        Allow .pdf, .txt, and .md extensions.
        Raise HTTPException(400) with message: "Only PDF, TXT and MD files are allowed."
        """
        filename = file.filename or ""
        _, ext = os.path.splitext(filename.lower())
        if ext not in [".pdf", ".txt", ".md"]:
            raise HTTPException(
                status_code=400,
                detail="Only PDF, TXT and MD files are allowed."
            )

    @staticmethod
    def validate_file_size(file: UploadFile) -> None:
        """
        Max file size: 10 MB (before parsing).
        Raise HTTPException(400) with message: "File size is too large. Please upload a smaller file."
        """
        try:
            # Move to end of file to determine size
            file.file.seek(0, 2)
            size = file.file.tell()
            # Reset seek position to start of file
            file.file.seek(0)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="File size is too large. Please upload a smaller file."
            )
        
        # 10 MB in bytes
        if size > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail="File size is too large. Please upload a smaller file."
            )

    @staticmethod
    def validate_empty_file(text: str) -> None:
        """
        Check if extracted text has length > 0.
        Raise HTTPException(400) with message: "The uploaded file is empty."
        """
        if not text or not text.strip():
            raise HTTPException(
                status_code=400,
                detail="The uploaded file is empty."
            )
