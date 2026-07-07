'use client';
import Link from 'next/link';
import {usePathname} from 'next/navigation';
const items:[string,string][]=[['/','Dashboard'],['/customers','Customers'],['/knowledge','Knowledge base'],['/questionnaires','Questionnaires'],['/settings','Settings']];
function isActive(href:string,path:string){
  if(href==='/')return path==='/';
  if(href==='/knowledge')return path.startsWith('/knowledge')||path.startsWith('/documents');
  return path.startsWith(href);
}
export default function Nav(){
  const path=usePathname();
  return <nav className="nav">{items.map(([href,label])=><Link key={href} href={href} className={isActive(href,path)?'active':''}>{label}</Link>)}</nav>;
}
