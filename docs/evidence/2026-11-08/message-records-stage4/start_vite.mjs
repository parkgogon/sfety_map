import { readFileSync } from 'node:fs';
import { createServer } from '/workspace/sfety_map/field_web/node_modules/vite/dist/node/index.js';
const apiPort=readFileSync('/workspace/analysis/contest/message-records-stage4/api-port.txt','utf8').trim();
const server=await createServer({root:'/workspace/sfety_map/field_web',define:{'import.meta.env.VITE_KAKAO_MAP_APP_KEY':JSON.stringify('local-sdk-fixture')},
 server:{host:'127.0.0.1',port:5177,strictPort:true,proxy:{'/api':`http://127.0.0.1:${apiPort}`,'/internal':`http://127.0.0.1:${apiPort}`}}});
await server.listen();server.printUrls();
