import { hasDemo } from "../demos/registry";
import { CATEGORY_LABELS } from "../data/types";
import type { Category, Project } from "../data/types";

export const CATEGORY_COLOR: Record<Category, string> = {
  "llm-platform": "var(--ai)",
  "systems": "var(--se)",
  "markets": "var(--mk)",
  "inference": "var(--ds)",
};

export function CategoryTag({ category }: { category: Category }) {
  return (
    <span className="tag" style={{ color: CATEGORY_COLOR[category] }}>
      {/* Dot plus label: the category never depends on colour alone. */}
      <span className="dot" style={{ background: CATEGORY_COLOR[category] }} />
      {CATEGORY_LABELS[category]}
    </span>
  );
}

interface Props {
  project: Project;
  onOpen: (project: Project) => void;
  baseUrl: string;
}

export function ProjectCard({ project, onOpen, baseUrl }: Props) {
  const shot = project.images?.[0];

  return (
    <button
      className={`card${project.featured ? " featured" : ""}`}
      onClick={() => onOpen(project)}
      aria-label={`Open details for ${project.title}`}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div className="card-head">
          <CategoryTag category={project.category} />
          {project.tests !== undefined && (
            <span className="tests">✓ {project.tests} tests</span>
          )}
          {hasDemo(project.slug) && <span className="live">▶ Demo</span>}
        </div>
        <h3>{project.title}</h3>
        <p>{project.summary}</p>
        <div className="techrow">
          {project.tech.slice(0, project.featured ? 8 : 5).map((t) => (
            <span className="tech" key={t}>
              {t}
            </span>
          ))}
          {project.tech.length > (project.featured ? 8 : 5) && (
            <span className="tech">
              +{project.tech.length - (project.featured ? 8 : 5)}
            </span>
          )}
        </div>
      </div>

      {project.featured && shot && (
        <img className="shot" src={`${baseUrl}${shot.src}`} alt={shot.alt} loading="lazy" />
      )}
    </button>
  );
}
