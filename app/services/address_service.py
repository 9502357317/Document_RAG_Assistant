from fastapi import HTTPException, UploadFile
from app.services.file_validator import FileValidator
from app.services.file_reader import FileParser
from app.services.smarty_api_client import SmartyAPIClient
from concurrent.futures import ThreadPoolExecutor

class AddressService:
    @staticmethod
    def chunk_text(text: str, max_chunk_size_bytes: int = 60000) -> list:
        """
        Split text into chunks, keeping each chunk's UTF-8 byte size under max_chunk_size_bytes.
        Splits by lines and words to avoid cutting an address, word, or line in half.
        """
        chunks = []
        current_chunk = []
        current_size = 0
        
        for line in text.splitlines(keepends=True):
            line_size = len(line.encode("utf-8"))
            
            if current_size + line_size <= max_chunk_size_bytes:
                current_chunk.append(line)
                current_size += line_size
            else:
                if current_chunk:
                    chunks.append("".join(current_chunk))
                    current_chunk = []
                    current_size = 0
                
                if line_size <= max_chunk_size_bytes:
                    current_chunk.append(line)
                    current_size = line_size
                else:
                    # Line itself exceeds max_chunk_size_bytes. Split by spaces/words.
                    words = line.split(" ")
                    for i, word in enumerate(words):
                        word_to_add = word + " " if i < len(words) - 1 else word
                        word_size = len(word_to_add.encode("utf-8"))
                        
                        if current_size + word_size <= max_chunk_size_bytes:
                            current_chunk.append(word_to_add)
                            current_size += word_size
                        else:
                            if current_chunk:
                                chunks.append("".join(current_chunk))
                                current_chunk = []
                                current_size = 0
                            
                            if word_size <= max_chunk_size_bytes:
                                current_chunk.append(word_to_add)
                                current_size = word_size
                            else:
                                # Single word exceeds max_chunk_size_bytes. Split by characters.
                                start = 0
                                while start < len(word_to_add):
                                    end = start
                                    char_bytes = 0
                                    while end < len(word_to_add):
                                        c_size = len(word_to_add[end].encode("utf-8"))
                                        if char_bytes + c_size > max_chunk_size_bytes:
                                            break
                                        char_bytes += c_size
                                        end += 1
                                    
                                    if end == start:
                                        end = start + 1
                                    
                                    chunks.append(word_to_add[start:end])
                                    start = end
                                current_chunk = []
                                current_size = 0
                                
        if current_chunk:
            chunks.append("".join(current_chunk))
            
        return chunks

    @staticmethod
    def process_file(file: UploadFile) -> list:
        """
        Process uploaded file: validate, parse text, chunk, and call Smarty API.
        Return list of Address objects.
        """
        try:
            # Step 1: Validate file type
            FileValidator.validate_file_type(file)
            
            # Step 2: Validate file size (10 MB max)
            FileValidator.validate_file_size(file)
            
            # Step 3: Parse file -> get text
            text = FileParser.read_file(file)
            
            # Step 4: Validate empty file
            FileValidator.validate_empty_file(text)
            
            # Step 5: Check if text size > 10 MB (10,485,760 bytes)
            if len(text.encode("utf-8")) > 10 * 1024 * 1024:
                raise HTTPException(
                    status_code=400,
                    detail="The file is too large to process. Please upload a smaller document."
                )
            
            return AddressService.process_text(text)
            
        except HTTPException as e:
            # Re-raise known HTTP exceptions
            raise e
        except Exception as e:
            # Catch other unexpected exceptions and wrap them as a 500 error
            raise HTTPException(
                status_code=500,
                detail="Something went wrong on server. Please try again later."
            )

    @staticmethod
    def process_text(text: str) -> list:
        """
        Process extracted text: chunk, and call Smarty API.
        Return list of Address objects.
        """
        try:
            # Step 6: Chunk the text to stay within Smarty API limit (64 KB)
            chunks = AddressService.chunk_text(text)
            
            # Helper to process a single chunk
            def process_chunk(chunk):
                if not chunk.strip():
                    return []
                req = SmartyAPIClient.build_request(chunk)
                res = SmartyAPIClient.send_request(req)
                return SmartyAPIClient.parse_response(res)

            addresses = []
            # Process chunks in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=10) as executor:
                results = executor.map(process_chunk, chunks)
                for chunk_addresses in results:
                    addresses.extend(chunk_addresses)
            
            # Step 7: Handle "No addresses found" scenario
            if not addresses:
                raise HTTPException(
                    status_code=400,
                    detail="No US addresses were found in the document."
                )
                
            return addresses
            
        except HTTPException as e:
            # Re-raise known HTTP exceptions
            raise e
        except Exception as e:
            # Catch other unexpected exceptions and wrap them as a 500 error
            raise HTTPException(
                status_code=500,
                detail="Something went wrong on server. Please try again later."
            )

    @staticmethod
    def extract_addresses(text: str) -> list:
        """
        Takes plain text string directly, finds addresses via Smarty API client,
        and returns a list of Address objects.
        """
        try:
            # Call Smarty API client to find addresses
            req = SmartyAPIClient.build_request(text)
            res = SmartyAPIClient.send_request(req)
            addresses = SmartyAPIClient.parse_response(res)
            
            # Handle "No addresses found" scenario
            if not addresses:
                raise HTTPException(
                    status_code=400,
                    detail="No US addresses were found in the document."
                )
                
            return addresses
            
        except HTTPException as e:
            raise e
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Something went wrong on server. Please try again later."
            )
