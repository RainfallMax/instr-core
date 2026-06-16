import { useState, useMemo } from "react";
import { CommandDef } from "../types";

interface SchemaCommandTreeProps {
  commands: CommandDef[];
  onSelectCommand?: (cmd: CommandDef) => void;
}

function formatParameterPreview(cmd: CommandDef): string {
  if (!cmd.parameters || cmd.parameters.length === 0) {
    if (cmd.range) {
      return `value [${cmd.range.min}, ${cmd.range.max}]`;
    }
    return "";
  }

  const param = cmd.parameters[0];
  let preview = `${param.name}: ${param.type}`;

  if (param.allowed_values && param.allowed_values.length > 0) {
    preview += ` [${param.allowed_values.join(", ")}]`;
  } else if (cmd.range) {
    preview += ` [${cmd.range.min}, ${cmd.range.max}]`;
  }

  return preview;
}

function truncateDescription(desc: string | undefined, maxLength: number = 60): string {
  if (!desc) return "";
  if (desc.length <= maxLength) return desc;
  return desc.substring(0, maxLength).trim() + "...";
}

export default function SchemaCommandTree({ commands, onSelectCommand }: SchemaCommandTreeProps) {
  const [searchQuery, setSearchQuery] = useState<string>("");

  const filteredCommands = useMemo(() => {
    const sorted = [...commands].sort((a, b) => a.command.localeCompare(b.command));

    if (!searchQuery.trim()) {
      return sorted;
    }

    const query = searchQuery.toLowerCase().trim();
    return sorted.filter((cmd) => {
      const nameMatch = cmd.command.toLowerCase().includes(query);
      const descMatch = cmd.description?.toLowerCase().includes(query) ?? false;
      const tagMatch = cmd.tags?.some((tag) => tag.toLowerCase().includes(query)) ?? false;
      return nameMatch || descMatch || tagMatch;
    });
  }, [commands, searchQuery]);

  return (
    <div className="schema-command-tree">
      <div className="command-search">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search commands..."
          className="search-input"
        />
        <span className="command-count">
          {filteredCommands.length} command{filteredCommands.length !== 1 ? "s" : ""}
        </span>
      </div>

      <ul className="command-list">
        {filteredCommands.map((cmd) => (
          <li
            key={cmd.command}
            className="command-item"
            onClick={() => onSelectCommand?.(cmd)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelectCommand?.(cmd);
              }
            }}
          >
            <div className="command-header">
              <code className="command-name">{cmd.command}</code>
              <span className="command-preview">{formatParameterPreview(cmd)}</span>
            </div>
            {cmd.description && (
              <p className="command-description">
                {truncateDescription(cmd.description)}
              </p>
            )}
            {cmd.tags && cmd.tags.length > 0 && (
              <div className="command-tags">
                {cmd.tags.map((tag) => (
                  <span key={tag} className="tag-pill">
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>

      {filteredCommands.length === 0 && (
        <div className="no-commands">
          <p>No commands match "{searchQuery}"</p>
        </div>
      )}
    </div>
  );
}
