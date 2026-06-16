import { CommandDetailProps } from "../types";

export default function CommandDetail({ command, onClose }: CommandDetailProps) {
  const hasParameters = command.parameters && command.parameters.length > 0;
  const hasRange = command.range != null;
  const hasRequires = command.requires && Object.keys(command.requires).length > 0;
  const hasForbidden = command.forbidden_when && Object.keys(command.forbidden_when).length > 0;
  const hasSafety = command.safety != null && (
    command.safety.compliance_required != null ||
    command.safety.compliance_parameter != null ||
    (command.safety.sequence && command.safety.sequence.length > 0)
  );
  const hasSetsState = command.sets_state && Object.keys(command.sets_state).length > 0;
  const hasTags = command.tags && command.tags.length > 0;

  return (
    <div className="command-detail-overlay" onClick={onClose}>
      <div className="command-detail-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="command-detail-header">
          <h3 className="command-detail-title">{command.command}</h3>
          <button className="command-detail-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        {/* Description */}
        {command.description && (
          <p className="command-detail-description">{command.description}</p>
        )}

        {/* Parameters */}
        {hasParameters && (
          <div className="command-detail-section">
            <h4 className="section-heading">Parameters</h4>
            <ul className="section-list">
              {command.parameters!.map((param) => (
                <li key={param.name} className="section-list-item">
                  <span className="bullet">•</span>
                  <code className="param-name">{param.name}</code>
                  <span className="param-type">{param.type}</span>
                  {param.allowed_values && (
                    <span className="param-values">
                      [{param.allowed_values.join(", ")}]
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Range */}
        {hasRange && (
          <div className="command-detail-section">
            <h4 className="section-heading">Range</h4>
            <span className="range-value">
              [{command.range!.min}, {command.range!.max}]
            </span>
          </div>
        )}

        {/* Requires */}
        {hasRequires && (
          <div className="command-detail-section">
            <h4 className="section-heading">Requires</h4>
            <ul className="section-list">
              {Object.entries(command.requires!).map(([key, value]) => (
                <li key={key} className="section-list-item">
                  <span className="bullet">•</span>
                  <code>{key}</code>
                  <span className="operator">=</span>
                  <span className="value">{value}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Forbidden when */}
        {hasForbidden && (
          <div className="command-detail-section">
            <h4 className="section-heading">Forbidden when</h4>
            <ul className="section-list">
              {Object.entries(command.forbidden_when!).map(([key, value]) => (
                <li key={key} className="section-list-item">
                  <span className="bullet">•</span>
                  <code>{key}</code>
                  <span className="operator">=</span>
                  <span className="value">{value}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Safety */}
        {hasSafety && (
          <div className="command-detail-section">
            <h4 className="section-heading">Safety</h4>
            <ul className="section-list">
              {command.safety!.compliance_required != null && (
                <li className="section-list-item">
                  <span className="bullet">•</span>
                  <span>Compliance required:</span>
                  <span className={command.safety!.compliance_required ? "value-true" : "value-false"}>
                    {command.safety!.compliance_required ? "true" : "false"}
                  </span>
                </li>
              )}
              {command.safety!.compliance_parameter && (
                <li className="section-list-item">
                  <span className="bullet">•</span>
                  <span>Compliance parameter:</span>
                  <code>{command.safety!.compliance_parameter}</code>
                </li>
              )}
              {command.safety!.sequence && command.safety!.sequence.length > 0 && (
                <li className="section-list-item sequence-item">
                  <span className="bullet">•</span>
                  <span>Sequence rules:</span>
                  <ul className="sequence-list">
                    {command.safety!.sequence.map((rule, idx) => (
                      <li key={idx} className="sequence-rule">
                        {rule.before && (
                          <div className="rule-line">
                            <span className="rule-label">before</span>
                            <code>{rule.before}</code>:
                          </div>
                        )}
                        {rule.after && (
                          <div className="rule-line">
                            <span className="rule-label">after</span>
                            <code>{rule.after}</code>:
                          </div>
                        )}
                        {rule.require_state_keys_present && (
                          <div className="rule-line">
                            <span className="rule-action">require_state_keys_present</span>
                            <span className="rule-value">
                              [{rule.require_state_keys_present.join(", ")}]
                            </span>
                          </div>
                        )}
                        {rule.expect_state && (
                          <div className="rule-line">
                            <span className="rule-action">expect_state</span>
                            <span className="rule-value">
                              {JSON.stringify(rule.expect_state)}
                            </span>
                          </div>
                        )}
                        <div className="rule-message">{rule.message}</div>
                      </li>
                    ))}
                  </ul>
                </li>
              )}
            </ul>
          </div>
        )}

        {/* Sets state */}
        {hasSetsState && (
          <div className="command-detail-section">
            <h4 className="section-heading">Sets state</h4>
            <ul className="section-list">
              {Object.entries(command.sets_state!).map(([key, value]) => (
                <li key={key} className="section-list-item">
                  <span className="bullet">•</span>
                  <code>{key}</code>
                  <span className="operator">=</span>
                  <span className="value">{value}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Tags */}
        {hasTags && (
          <div className="command-detail-section tags-section">
            {command.tags!.map((tag) => (
              <span key={tag} className="tag-pill">
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
