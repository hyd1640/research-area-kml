"""Make a standalone offline pixel digitizer; no map is uploaded."""
import argparse
import base64
import io
from pathlib import Path
from PIL import Image


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    a=p.parse_args()
    im=Image.open(a.image).convert('RGB');buf=io.BytesIO();im.save(buf,format='PNG')
    data=base64.b64encode(buf.getvalue()).decode()
    html='''<!doctype html><meta charset="utf-8"><title>Pixel boundary digitizer</title>
<style>body{font:16px system-ui;margin:20px;background:#eee}canvas{max-width:100%;height:auto;background:white;cursor:crosshair}button{padding:8px;margin:4px}textarea{width:95%;height:120px}</style>
<h1>Pixel boundary digitizer</h1><p>Click points along the visible outer boundary. Image coordinates remain in original pixels. Add rings for holes or other polygons; assign their roles explicitly in the final config.</p>
<button id="undo">Undo</button><button id="next">New ring</button><button id="save">Download points</button><span id="position"></span><br>
<canvas id="c"></canvas><textarea id="output" readonly></textarea>
<script>
const im=new Image(),c=document.getElementById('c'),ctx=c.getContext('2d');let rings=[[]];
function redraw(){ctx.drawImage(im,0,0);ctx.strokeStyle='#ff6600';ctx.lineWidth=3;for(const ring of rings){ctx.beginPath();ring.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.stroke();for(const [x,y] of ring){ctx.fillStyle='#00ffff';ctx.fillRect(x-2,y-2,4,4);}}document.getElementById('output').value=JSON.stringify({image_size:[im.width,im.height],rings_pixels:rings},null,2);}
function pos(e){const r=c.getBoundingClientRect();return [Math.round((e.clientX-r.left)*im.width/r.width),Math.round((e.clientY-r.top)*im.height/r.height)];}
c.onclick=e=>{rings.at(-1).push(pos(e));redraw();};c.onmousemove=e=>document.getElementById('position').textContent=pos(e).join(', ');
document.getElementById('undo').onclick=()=>{rings.at(-1).pop();redraw();};document.getElementById('next').onclick=()=>{if(rings.at(-1).length){rings.push([]);redraw();}};
document.getElementById('save').onclick=()=>{const a=document.createElement('a'),u=URL.createObjectURL(new Blob([document.getElementById('output').value],{type:'application/json'}));a.href=u;a.download='boundary_pixels.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
im.onload=()=>{c.width=im.width;c.height=im.height;redraw();};im.src='data:image/png;base64,IMAGE_DATA';
</script>'''.replace('IMAGE_DATA',data)
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(html,encoding='utf-8')
    print(a.out)


if __name__=='__main__':
    main()
