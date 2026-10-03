import { BookOpen, Github } from "lucide-react";

const source = "https://github.com/vercel-labs/notebook-factory";
const components = [
  { name: "Supabase", url: "https://supabase.com/", text: "Postgres stores users, notebook documents and outputs, published revisions, chat history, and editor sessions. It also powers full-text search across notebook titles and content." },
  { name: "Vercel CDN", url: "https://vercel.com/docs/cdn", text: "Serves the React application's static HTML, JavaScript, and CSS." },
  { name: "Vercel + FastAPI", url: "https://vercel.com/docs/frameworks/backend/fastapi", text: "Runs FastAPI on Vercel Fluid Serverless platform." },
  { name: "Vercel Blob", url: "https://vercel.com/docs/vercel-blob", text: "Stores rendered notebook HTML and prepared font assets. Published notebooks can be read without starting a kernel." },
  { name: "Vercel AI Gateway", url: "https://vercel.com/docs/ai-gateway", text: "Routes model requests from the backend, authenticated with the deployment's Vercel identity." },
  { name: "Vercel Python AI SDK", url: "https://github.com/vercel-labs/ai-python", text: "Runs the agent's model and tool loop, streaming responses to the browser. Tools read, edit, and execute notebook cells." },
  { name: "Vercel AI SDK UI", url: "https://ai-sdk.dev/docs/ai-sdk-ui/overview", text: "React useChat and its transport handle streamed messages, tool progress, and tool results in the chat panel." },
  { name: "Vercel Sandbox", url: "https://vercel.com/docs/vercel-sandbox", text: "Runs JupyterLab in one isolated VM per user, with a separate kernel per notebook. The Vercel Python Sandbox SDK manages VM lifecycle, commands, and workspace drives." },
  { name: "Jupyter Notebooks", url: "https://jupyter.org/", text: "Standard .ipynb files contain code, Markdown, and execution outputs. JupyterLab provides the embedded editor; nbconvert renders published HTML." },
  { name: "lat.md", url: "/lat/", text: "Repository documentation links architecture, design decisions, and test specifications to implementation symbols." },
];

export function About({ onBack }: { onBack: () => void }) {
  return <article className="about-page" aria-labelledby="about-title">
    <div className="about-content">
      <nav className="about-nav" aria-label="About page">
        <a href="/" onClick={event => { if (!event.metaKey && !event.ctrlKey) { event.preventDefault(); onBack(); } }}>← Notebooks</a>
      </nav>
      <h1 id="about-title">How it works</h1>
      <p className="about-summary">React frontend, Python API, Jupyter execution in ▲ Sandbox. The agent edits notebook cells; documents are saved to Postgres and rendered HTML is published to ▲ Blob.</p>
      <a className="about-source button" href={source} target="_blank" rel="noopener noreferrer"><Github size={16} aria-hidden="true" />View source on GitHub</a>
      <a className="about-source button" href="/lat/"><BookOpen size={16} aria-hidden="true" />See lat.md project docs</a>
      <dl className="about-stack" aria-label="Technology stack">
        {components.map(({ name, url, text }) => <div className="about-component" key={name}>
          <dt><a href={url} target="_blank" rel="noopener noreferrer" aria-label={name}>{name.replaceAll("Vercel", "▲")}</a></dt>
          <dd>{text.replaceAll("Vercel", "▲")}</dd>
        </div>)}
      </dl>
    </div>
  </article>;
}
