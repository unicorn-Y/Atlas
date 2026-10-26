/** Keep the post-run skill prompt quiet unless the finished turn contains reusable work. */
const EXPLICIT_POSITIVE_FEEDBACK = /(?:谢谢|太好了|非常好|做得好|不错|完美|正是我想要|这就对了|解决了|满意|great job|perfect|that works|exactly what i wanted|thanks,? that)/i;
const CORRECTION = /(?:不对|不是这样|还不对|再改|重新来|仍然|还是不|修正|纠正|doesn't work|not right|try again|fix this|that's wrong)/i;

export function shouldSuggestSkillExtraction(
  events: ReadonlyArray<{ type: string; id?: string }>,
  userMessages: ReadonlyArray<string>,
): boolean {
  const toolSteps = new Set(events.map((event, index) => event.type === 'tool.started' ? event.id ?? `tool-${index}` : '').filter(Boolean));
  if (toolSteps.size >= 2) return true;

  const recent = userMessages.slice(-6);
  if (recent.filter((message) => CORRECTION.test(message)).length >= 2 && toolSteps.size >= 1) return true;

  return recent.slice(-3).some((message) => EXPLICIT_POSITIVE_FEEDBACK.test(message));
}
