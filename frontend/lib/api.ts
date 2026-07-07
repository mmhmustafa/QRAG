import {formatError} from './errors';
export const API=process.env.NEXT_PUBLIC_API_URL||'http://localhost:8000';

async function payload(response:Response):Promise<unknown>{const text=await response.text();if(!text)return undefined;try{return JSON.parse(text)}catch{return text}}

async function request(path:string,init:RequestInit={}):Promise<any>{
  const method=(init.method||'GET').toUpperCase(),url=API+path;
  try{
    const response=await fetch(url,init),body=await payload(response);
    if(!response.ok){
      const detail=formatError(body||`${response.status} ${response.statusText}`),message=response.status===404?`API endpoint not found: ${path}`:detail;
      if(process.env.NODE_ENV!=='production')console.error('[API]',{method,url,status:response.status,errorBody:body,message});
      const failure=new Error(message) as Error&{apiLogged?:boolean};failure.apiLogged=true;throw failure;
    }
    if(process.env.NODE_ENV!=='production')console.debug('[API]',{method,url,status:response.status});
    return body;
  }catch(error){
    if(error instanceof Error&&(error as Error&{apiLogged?:boolean}).apiLogged)throw error;
    const message=formatError(error);
    if(process.env.NODE_ENV!=='production')console.error('[API]',{method,url,status:0,errorBody:message});
    throw new Error(message);
  }
}

export async function get(path:string){return request(path,{cache:'no-store'})}
export async function send(path:string,method:string,body?:unknown){return request(path,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)})}
export async function upload(path:string,file:File,extra:Record<string,string>={}){const form=new FormData();form.append('file',file);Object.entries(extra).forEach(([key,value])=>form.append(key,String(value)));return request(path,{method:'POST',body:form})}
