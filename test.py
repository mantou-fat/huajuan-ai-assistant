import requests, os, math
from dotenv import load_dotenv
load_dotenv()

def embed_text(text):
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
    headers = {"Authorization": "Bearer " + os.getenv("DASHSCOPE_API_KEY")}
    r = requests.post(url, headers=headers,
        json={"model": "text-embedding-v3", "input": text}, timeout=30)
    return r.json()["data"][0]["embedding"]

def cos_sim(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(y*y for y in b))
    return dot / (na * nb)

v1 = embed_text("今天天气怎么样")
v2 = embed_text("外面下雨了吗")   # 语义近
v3 = embed_text("我想吃红烧肉")   # 语义远
print("近:", round(cos_sim(v1, v2), 3))
print("远:", round(cos_sim(v1, v3), 3))


          
 
      
 



