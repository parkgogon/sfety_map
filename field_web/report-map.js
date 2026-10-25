import "./report-map.css";
const key = import.meta.env.VITE_KAKAO_MAP_APP_KEY?.trim();
const mapsReady = new Promise((resolve, reject) => {
  if (!key) { reject(new Error("지도 설정을 확인하지 못했습니다.")); return; }
  const script = document.createElement("script");
  script.src = "https://dapi.kakao.com/v2/maps/sdk.js?autoload=false&appkey=" + encodeURIComponent(key);
  script.onload = () => window.kakao?.maps ? kakao.maps.load(resolve) : reject(new Error("지도 초기화 실패"));
  script.onerror = () => reject(new Error("지도 로딩 실패"));
  document.head.append(script);
});
// A failed SDK request is handled when renderReportMap awaits it.
mapsReady.catch(() => {});

window.renderReportMap = async function(data) {
  await mapsReady;
  await document.fonts.ready;
  const el=document.getElementById('map'),ll=p=>new kakao.maps.LatLng(p.latitude,p.longitude);
  const center=ll(data),map=new kakao.maps.Map(el,{center,level:8,draggable:false,scrollwheel:false,disableDoubleClickZoom:true});
  const bounds=new kakao.maps.LatLngBounds();data.circle.forEach(p=>bounds.extend(ll(p)));
  map.setBounds(bounds,62,76,62,76);
  new kakao.maps.Polygon({map,path:data.circle.map(ll),strokeWeight:2,strokeColor:'#0284c7',strokeOpacity:.9,fillColor:'#38bdf8',fillOpacity:.035});
  const projection=map.getProjection(),centerPx=projection.containerPointFromCoords(center);
  const groups=[];
  for(const facility of data.facilities) {
    const px=projection.containerPointFromCoords(ll(facility));
    let group=groups.find(g=>Math.hypot(g.x-px.x,g.y-px.y)<38);
    if(!group){group={number:groups.length+1,x:px.x,y:px.y,latitude:facility.latitude,longitude:facility.longitude,ids:[],numbers:[]};groups.push(group)}
    group.ids.push(facility.id);group.numbers.push(facility.number);
    const dot=document.createElement('div');dot.className='actual-dot';
    new kakao.maps.CustomOverlay({map,position:ll(facility),content:dot,xAnchor:.5,yAnchor:.5,zIndex:2});
  }
  const occupied=[{x:centerPx.x-15,y:centerPx.y-18,w:123,h:40},
                  {x:0,y:0,w:435,h:62},{x:1120,y:0,w:80,h:110},
                  {x:0,y:588,w:200,h:32}];
  const collides=(a,b)=>a.x<b.x+b.w+4&&a.x+a.w+4>b.x&&a.y<b.y+b.h+4&&a.y+a.h+4>b.y;
  for(const group of groups) {
    const wrap=document.createElement('div');wrap.className='badge-wrap';
    const badge=document.createElement('div');badge.className='badge';badge.textContent=String(group.number);
    if(group.ids.length>1){const count=document.createElement('small');count.textContent='· '+group.ids.length+'개소';badge.append(count)}
    wrap.append(badge);new kakao.maps.CustomOverlay({map,position:ll(group),content:wrap,xAnchor:.5,yAnchor:.5,zIndex:5});
    const width=badge.getBoundingClientRect().width;
    const offsets=[[0,0]];
    for(let distance=40;distance<=240;distance+=24)
      for(let angle=0;angle<16;angle++)offsets.push([Math.cos(angle*Math.PI/8)*distance,Math.sin(angle*Math.PI/8)*distance]);
    const offset=offsets.find(([dx,dy])=>{const box={x:group.x+dx-width/2,y:group.y+dy-15,w:width,h:30};
      return box.x>=6&&box.x+width<=1194&&box.y>=6&&box.y+30<=584&&!occupied.some(o=>collides(box,o))});
    if(!offset)throw Error('시설 번호를 겹침 없이 배치할 수 없습니다.');
    const [dx,dy]=offset;badge.style.transform=`translate(calc(-50% + ${dx}px),calc(-50% + ${dy}px))`;
    occupied.push({x:group.x+dx-width/2,y:group.y+dy-15,w:width,h:30});
    if(dx||dy){
      const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),line=document.createElementNS(ns,'line');
      svg.style.cssText='position:absolute;left:0;top:0;width:1px;height:1px;overflow:visible;pointer-events:none';
      for(const [name,value] of Object.entries({x1:15,y1:15,x2:15+dx,y2:15+dy,stroke:'#0f766e','stroke-width':1.3}))line.setAttribute(name,String(value));
      svg.append(line);wrap.prepend(svg);
    }
    group.offset={x:dx,y:dy};
  }
  const marker=document.createElement('div');marker.className='point';
  const name=document.createElement('span');name.className='point-label';name.textContent='기준점';marker.append(name);
  new kakao.maps.CustomOverlay({map,position:center,content:marker,xAnchor:.5,yAnchor:.5,zIndex:10});
  const radius=document.createElement('div');radius.className='radius-label';radius.textContent='반경 '+data.radius_km+'km';
  new kakao.maps.CustomOverlay({map,position:ll(data.circle[0]),content:radius,xAnchor:.5,yAnchor:1,zIndex:6});
  const north=document.createElement('div');north.className='north';north.innerHTML='<b>↑</b>북 N';el.append(north);
  const caption=document.createElement('div');caption.className='map-caption';
  const title=document.createElement('strong');title.textContent='기준점 주변 시설 위치도';caption.append(title,document.createTextNode('  ·  직선 반경 '+data.radius_km+'km'));el.append(caption);
  window.__reportMap={map,data,groups};
  return {level:map.getLevel(),groups:groups.map(({number,ids,numbers,offset})=>({number,ids,numbers,offset})),
          circlePixels:data.circle.map(p=>{const q=projection.containerPointFromCoords(ll(p));return {x:q.x,y:q.y}}),
          center:{x:centerPx.x,y:centerPx.y},width:1200,height:620};
};

window.nearbyMapVersion = 1;
