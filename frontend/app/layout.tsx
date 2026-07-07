import './globals.css';import './upload.css';import './polish.css';import './reviewer.css';
import Link from 'next/link';import {CustomerProvider} from '../components/CustomerContext';import CustomerSwitch from '../components/CustomerSwitch';import Nav from '../components/Nav';
export const metadata={title:'Customer Questionnaire Assistant',description:'Grounded questionnaire answers from approved knowledge'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body><CustomerProvider><div className="shell"><aside className="side"><Link className="logo" href="/"><span>◈</span> Customer<br/>Questionnaire Assistant</Link><CustomerSwitch/><Nav/></aside><main className="main">{children}</main></div></CustomerProvider></body></html>}
