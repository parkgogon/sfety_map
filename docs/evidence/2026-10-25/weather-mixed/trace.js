(() => {
 const entry=window.__realSdkMaps[0],surface=document.querySelector('.weather-map-surface'),ctx=surface.getContext('2d');
 const trace=window.__weatherTrace={generation:0,labels:[],samples:[],overlay:null};
 const fill=ctx.fillText.bind(ctx),clear=ctx.clearRect.bind(ctx);
 ctx.fillText=(text,x,y,...rest)=>{trace.labels.push({text,x,y,generation:trace.generation});return fill(text,x,y,...rest)};
 ctx.clearRect=(...args)=>{trace.generation++;trace.labels=[];return clear(...args)};
 trace.pin=()=>{
  if(!trace.labels.length)throw Error('표시된 수치 없음');
  const label=trace.labels[0],left=parseFloat(surface.style.left),top=parseFloat(surface.style.top);
  const projection=entry.map.getProjection();
  const coordinate=projection.coordsFromContainerPoint(new kakao.maps.Point(label.x+left,label.y+top));
  const dot=document.createElement('div');dot.style='width:8px;height:8px;border:2px solid #d252a2;border-radius:50%;box-sizing:border-box;pointer-events:none';
  trace.overlay?.setMap(null);trace.overlay=new kakao.maps.CustomOverlay({map:entry.map,position:coordinate,content:dot,xAnchor:.5,yAnchor:.5,zIndex:999});
  trace.pinElement=dot;trace.label=label;trace.coordinate=coordinate;trace.pinGeneration=trace.generation;return {label,latitude:coordinate.getLat(),longitude:coordinate.getLng()};
 };
 trace.start=()=>{trace.samples=[];trace.running=true;
 const base=entry.element.getBoundingClientRect(),left=parseFloat(surface.style.left),top=parseFloat(surface.style.top);
 const front=document.elementsFromPoint(base.left+base.width/2,base.top+base.height/2).find(i=>i.tagName==='IMG'&&i.src.includes('/tile/')&&entry.element.contains(i));
 const tiles=[...entry.element.querySelectorAll('img')].filter(i=>{const r=i.getBoundingClientRect();return i.parentElement===front.parentElement&&i.src.includes('/tile/')&&i.checkVisibility({opacityProperty:true,visibilityProperty:true})&&r.right>base.left&&r.left<base.right&&r.bottom>base.top&&r.top<base.bottom}).map(image=>{const r=image.getBoundingClientRect();return {image,src:image.src,x:r.x-base.x-left,y:r.y-base.y-top}});
 function step(time){if(!trace.running)return;setTimeout(()=>{
   if(!trace.running)return;
   const rect=trace.pinElement.getBoundingClientRect(),base=entry.element.getBoundingClientRect(),matrix=new DOMMatrix(getComputedStyle(surface).transform);
   const point=new DOMPoint(trace.label.x,trace.label.y).matrixTransform(matrix);
   const x=base.left+parseFloat(surface.style.left)+point.x,y=base.top+parseFloat(surface.style.top)+point.y;
   const tileErrors=tiles.filter(t=>t.image.isConnected&&t.image.src===t.src&&t.image.getBoundingClientRect().width>0).map(t=>{const p=new DOMPoint(t.x,t.y).matrixTransform(matrix),r=t.image.getBoundingClientRect();return Math.hypot(base.left+left+p.x-r.x,base.top+top+p.y-r.y)});
   trace.samples.push({time,generation:trace.generation,sameGeneration:trace.generation===trace.pinGeneration,x,y,nativeX:rect.x+rect.width/2,nativeY:rect.y+rect.height/2,nativeVisible:rect.width>0&&rect.height>0,error:Math.hypot(x-(rect.x+rect.width/2),y-(rect.y+rect.height/2)),tileError:Math.max(0,...tileErrors),matrix:surface.style.transform,opacity:getComputedStyle(surface).opacity,level:entry.map.getLevel()});
  },0);requestAnimationFrame(step);
 }requestAnimationFrame(step)};
 trace.stop=()=>{trace.running=false;return trace.samples};
})();
