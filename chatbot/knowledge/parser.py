import re

def clean_markdown(content: str) -> list[str]:
    """
    Cleansing konten markdown dan membaginya menjadi beberapa halaman.
    """
    # Pisahkan berdasarkan pemisah page break
    pages = content.split("<!-- page break -->")
    
    cleaned_pages = []
    for page in pages:
        # Hapus spasi kosong di awal dan akhir
        page = page.strip()
        
        # Hapus baris kosong yang berlebihan
        page = re.sub(r'\n{3,}', '\n\n', page)
        
        # Tambahkan tagging <question> dan <answer> agar AI RAG tidak bingung
        q_match = re.search(r'^Q:\s*(.*?)(?=\n\n|\n<query>|$)', page, flags=re.DOTALL)
        if q_match:
            question = q_match.group(1).strip()
            page_no_q = page[q_match.end():].strip()
            
            if "<query>" in page_no_q:
                ans_text, query_text = page_no_q.split("<query>", 1)
                query_text = "<query>" + query_text
            else:
                ans_text = page_no_q
                query_text = ""
                
            ans_text = ans_text.strip()
            
            new_page = f"<question>{question}</question>\n"
            if ans_text:
                new_page += f"<answer>{ans_text}</answer>\n"
            if query_text:
                new_page += f"{query_text}"
                
            page = new_page.strip()
        
        # Jika halaman tidak kosong setelah dibersihkan, masukkan ke list
        if page:
            cleaned_pages.append(page)
            
    return cleaned_pages
