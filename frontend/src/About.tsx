import { ArrowLeft, ArrowUpRight, BookOpen, Box, Braces, Database, FileText, Github, Globe, Layers, MessageSquare, Network, Terminal } from "lucide-react";

const source = "https://github.com/vercel-labs/notebook-factory";
const components = [
  { name: "Vercel CDN", role: "THE FRONT DOOR", icon: Globe, url: "https://vercel.com/docs/cdn", text: "Serves the built React application, JavaScript, and CSS as static assets. The interface reaches your browser through Vercel’s global delivery network." },
  { name: "Vercel + FastAPI", role: "THE APPLICATION BACKEND", icon: Braces, url: "https://vercel.com/docs/frameworks/backend/fastapi", text: "Vercel hosts and runs our Python API, built with FastAPI. It handles authentication, notebook permissions, saving, publishing, and coordination of the AI and execution services." },
  { name: "Supabase", role: "THE SOURCE OF TRUTH", icon: Database, url: "https://supabase.com/", text: "Supabase Postgres is the main database for accounts, notebook documents, published revisions, and chat history. Drafts and outputs are saved here so they survive a temporary execution environment." },
  { name: "Vercel Blob", role: "THE PUBLISHED ARTIFACTS", icon: Layers, url: "https://vercel.com/docs/vercel-blob", text: "Stores rendered notebook HTML for fast, public reading, plus prepared font assets for the Python environment. Opening a published notebook does not need to start a Python kernel." },
  { name: "AI Gateway", role: "THE MODEL CONNECTION", icon: Network, url: "https://vercel.com/docs/ai-gateway", text: "Routes the assistant’s inference requests to the configured model through one Vercel endpoint. The backend authenticates using the deployment’s Vercel identity." },
  { name: "Python AI SDK", role: "THE AGENT ON THE SERVER", icon: Terminal, url: "https://github.com/vercel-labs/ai-python", text: "Streams model responses and tool requests from Python through AI Gateway. Notebook tools let the assistant read cells, write code, and request execution in the live editor." },
  { name: "AI SDK UI", role: "THE CONVERSATION IN YOUR BROWSER", icon: MessageSquare, url: "https://ai-sdk.dev/docs/ai-sdk-ui/overview", text: "The React useChat hook and streaming transport power the chat interface. They turn the Python response stream into messages, tool progress, and cell-edit previews, and send tool results back to the agent." },
  { name: "Vercel Sandbox", role: "THE PYTHON EXECUTION ENVIRONMENT", icon: Box, url: "https://vercel.com/docs/vercel-sandbox", text: "Runs JupyterLab and Python in an isolated VM, shared across a user’s notebooks with a separate kernel for each. The Python Sandbox SDK provisions the runtime and manages its lifecycle, while prepared dependencies and workspace drives speed up reopening." },
  { name: "Jupyter Notebooks", role: "THE WORKING DOCUMENT", icon: BookOpen, url: "https://jupyter.org/", text: "Standard .ipynb documents keep code, Markdown, charts, and execution results together. JupyterLab provides the live editor; published HTML lets everyone read the result without running the notebook." },
  { name: "lat.md", role: "THE ARCHITECTURE MAP", icon: FileText, url: `${source}/tree/main/lat.md`, text: "Linked Markdown documents describe the architecture, design decisions, and test expectations beside the code. We use them to keep implementation work grounded and check that documentation references stay valid." },
];

export function About({ onBack }: { onBack: () => void }) {
  return <article className="about-page" aria-labelledby="about-title">
    <nav className="about-nav" aria-label="About page">
      <a href="/" onClick={event => { if (!event.metaKey && !event.ctrlKey) { event.preventDefault(); onBack(); } }}><ArrowLeft size={14} />Notebooks</a>
      <a href={source} target="_blank" rel="noopener noreferrer"><Github size={15} />View source<ArrowUpRight size={13} /></a>
    </nav>
    <header className="about-hero">
      <div className="about-eyebrow"><span /> UNDER THE HOOD</div>
      <h1 id="about-title">A notebook is just<br />the beginning<span>.</span></h1>
      <p>Real Python. A live Jupyter environment. An agent that works in the document.<br className="about-desktop-break" /> Here’s how Python Notebooks brings it all together.</p>
      <a className="button primary" href={source} target="_blank" rel="noopener noreferrer"><Github size={15} />Explore the code<ArrowUpRight size={14} /></a>
      <div className="about-orbit" aria-hidden="true"><svg viewBox="0 0 120 104"><path d="M60 0L120 104H0Z" fill="none" stroke="currentColor" /></svg></div>
    </header>
    <section className="about-flow" aria-label="From browser to published notebook">
      {[
        ["01", "Open", "React + Vercel CDN", "The workspace arrives in your browser."],
        ["02", "Ask", "AI SDK + AI Gateway", "The agent reads and edits your notebook."],
        ["03", "Run", "Sandbox + Jupyter", "Python executes in your own environment."],
        ["04", "Publish", "Supabase + Blob", "Save the document. Share the rendered result."],
      ].map(([number, title, stack, detail]) => <div className="about-step" key={number}><span className="about-step-number">{number}</span><h2>{title}</h2><strong>{stack}</strong><p>{detail}</p></div>)}
    </section>
    <div className="about-section-title"><h2>One workspace. A few good building blocks.</h2><span>THE STACK</span></div>
    <section className="about-stack" aria-label="Technology stack">
      {components.map(({ name, role, icon: Icon, url, text }) => <a className="about-component" key={name} href={url} target="_blank" rel="noopener noreferrer">
        <div className="about-component-top"><Icon size={20} strokeWidth={1.4} /><ArrowUpRight size={14} /></div>
        <span className="about-role">{role}</span><h3>{name}</h3><p>{text}</p>
      </a>)}
    </section>
    <footer className="about-footer"><span>Built on Vercel. Built around Python.</span><a href={`${source}/tree/main/lat.md`} target="_blank" rel="noopener noreferrer">Read the architecture docs<ArrowUpRight size={13} /></a></footer>
  </article>;
}
