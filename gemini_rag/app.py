from flask import Flask,request,jsonify
from database import initialize_database,get_all_files
from rag import get_or_create_store,query_rag
app=Flask(__name__); initialize_database(); STORE_NAME=get_or_create_store().name
@app.get('/')
def home(): return jsonify({'status':'running','model':'gemini-3.5-flash-lite','store':STORE_NAME})
@app.post('/query')
def query():
 try:
  data=request.get_json(silent=True) or {}; q=data.get('question','').strip()
  if not q:return jsonify({'error':"Missing 'question'."}),400
  r=query_rag(q,STORE_NAME); return jsonify({'success':True,'question':q,**r})
 except Exception as e:return jsonify({'success':False,'error':str(e)}),500
@app.get('/files')
def files():
 return jsonify({'count':len(get_all_files()),'files':[dict(r) for r in get_all_files()]})
if __name__=='__main__': app.run(host='127.0.0.1',port=5000,debug=True)
