import "./CitedText.css";

const CITATION_RE = /\[E(\d+)\]/g;

export default function CitedText({ text }: { text: string }) {
  const parts: (string | { id: number })[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  CITATION_RE.lastIndex = 0;
  while ((match = CITATION_RE.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
    parts.push({ id: Number(match[1]) });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));

  return (
    <p className="cited-text">
      {parts.map((part, i) =>
        typeof part === "string" ? (
          <span key={i}>{part}</span>
        ) : (
          <a key={i} href={`#evidence-${part.id}`} className="citation-chip">
            E{part.id}
          </a>
        )
      )}
    </p>
  );
}
