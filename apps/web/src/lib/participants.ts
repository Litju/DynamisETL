import type { SessionDetail } from "@/api/types";

/**
 * Compact display label for a registered participant note.
 *
 * Football providers register notes as `shirt 16 (Christopher Schindler)`;
 * charts read better as `Christopher Schindler #16`. Any other registered
 * note is shown as-is, and no label is invented when none is registered.
 */
export function compactParticipantLabel(note: string | null | undefined): string | null {
  if (!note) return null;
  const match = /^shirt\s+(\d+)\s+\((.+)\)$/i.exec(note.trim());
  return match ? `${match[2]} #${match[1]}` : note;
}

/** Map entity/subject ids to compact registered labels for one session. */
export function participantLabels(session: SessionDetail | undefined): ReadonlyMap<string, string> {
  const labels = new Map<string, string>();
  for (const participant of session?.participants ?? []) {
    const label = compactParticipantLabel(participant.notes);
    if (label) labels.set(participant.subject_id, label);
  }
  return labels;
}

/** Resolve a provider identity to its registered participant id, never its display name. */
export function verifiedParticipant(session: SessionDetail | undefined, providerIds: readonly string[]): string | null {
  if (!session) return null;
  const ids = new Set(providerIds);
  return session.participants.find((participant) => ids.has(participant.subject_id))?.subject_id ?? null;
}
