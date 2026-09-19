/** Minimal class-name join; avoids a utility dependency for one expression. */
export function cn(...values: Array<string | false | null | undefined>): string {
  return values.filter((value): value is string => Boolean(value)).join(" ");
}
