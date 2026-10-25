import { messages as enUS } from './en-US';

// Chinese is the source locale; explicit identities keep every catalog key addressable.
export const messages: Record<string, string> = Object.fromEntries(Object.keys(enUS).map((key) => [key, key]));
