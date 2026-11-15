"""CSV validation and programmatic plots; never execute model-generated code."""
import base64
import csv
import io
import json
import math
import os
import threading
import tempfile
from typing import Literal
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

router=APIRouter(prefix='/api/library',tags=['charts'])
_PLOT_LOCK=threading.Lock()

@router.post('/chart')
def chart(file: UploadFile=File(...), x: str=Form(...), y: str=Form(...), kind: Literal['line','bar']=Form(default='line')):
    try: data=file.file.read(1024*1024+1)
    finally: file.file.close()
    if len(data)>1024*1024: raise HTTPException(413,'CSV 限制为 1 MiB。')
    try:
        reader=csv.DictReader(io.StringIO(data.decode('utf-8-sig')),strict=True)
        fields=reader.fieldnames or []
        if len(fields)>50 or len(set(fields))!=len(fields) or any(not f or len(f)>100 for f in fields): raise ValueError('列名重复或列数超过 50。')
        if x not in fields or y not in fields: raise ValueError('请选择 CSV 中确实存在的 X/Y 列。')
        rows=[]
        for row in reader:
            if len(rows)>=1000: raise ValueError('图表最多支持 1000 行，请先筛选。')
            if None in row or any(v is None for v in row.values()): raise ValueError('CSV 行列数量不一致。')
            value=float(row[y])
            if not math.isfinite(value) or abs(value)>1e100: raise ValueError('Y 列必须是有限数值，不能含 NaN/Infinity。')
            if len(row[x])>120: raise ValueError('X 标签过长。')
            rows.append((row[x],value))
        if not rows: raise ValueError('CSV 没有数据行。')
    except (ValueError,UnicodeError,csv.Error) as error: raise HTTPException(422,'CSV 无法绘图：'+str(error)) from error
    labels=[r[0] for r in rows]; values=[r[1] for r in rows]
    os.environ.setdefault('MPLCONFIGDIR',str(__import__('pathlib').Path(tempfile.gettempdir())/'tracescholar-matplotlib'))
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    with _PLOT_LOCK:
        figure=Figure(figsize=(9,4.8),layout='constrained'); FigureCanvasAgg(figure)
        ax=figure.subplots(); ax.set_facecolor('#f8f9fc')
        positions=list(range(len(rows)))
        if kind=='line': ax.plot(positions,values,color='#5965d8',linewidth=2)
        else: ax.bar(positions,values,color='#5965d8')
        ticks=positions[::max(1,len(rows)//12)]
        ax.set_xticks(ticks, [labels[i] for i in ticks],rotation=25,ha='right',parse_math=False)
        ax.set_xlabel(x,parse_math=False); ax.set_ylabel(y,parse_math=False); ax.grid(axis='y',alpha=.2)
        buffer=io.BytesIO(); figure.savefig(buffer,format='png',dpi=160)
    low=min(values); high=max(values); mean=sum(v/len(values) for v in values)
    caption=(f'{y} 随 CSV 行序的观测值（{len(rows)} 个数据点）。最小值 {low:g}，最大值 {high:g}，均值 {mean:g}。'
             '未进行显著性检验；图中变化不代表因果关系。')
    # The downloadable script is a fixed template, with untrusted strings encoded as JSON literals.
    script=('import json\nimport matplotlib.pyplot as plt\n'
            'data = json.loads('+repr(json.dumps(rows,ensure_ascii=True))+')\n'
            'labels, values = zip(*data)\nfig, ax = plt.subplots(figsize=(9, 4.8), layout="constrained")\n'
            +('ax.plot(range(len(values)), values)\n' if kind=='line' else 'ax.bar(range(len(values)), values)\n')
            +'ax.set_xlabel('+repr(x)+', parse_math=False)\nax.set_ylabel('+repr(y)+', parse_math=False)\n'
            'ax.set_xticks(range(len(labels)), labels, rotation=25, parse_math=False)\nfig.savefig("figure.png", dpi=160)\n')
    return {'image':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(),
            'caption':caption,'script':script,'rows':len(rows),'stats':{'min':low,'max':high,'mean':mean},
            'method':'固定 Matplotlib 模板；数值由程序计算，未调用模型或执行上传代码'}
