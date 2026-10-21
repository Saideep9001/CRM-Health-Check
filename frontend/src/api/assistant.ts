import type { CrmAnswer } from '@/types';
import { http } from './client';

/**
 * Help assistant API. See docs/API_CONTRACT.md → Help assistant.
 * The assistant is a built-in guide plus fixed, read-only Salesforce lookups (no AI).
 */

export interface AssistantStatus {
  mode: 'ai' | 'guide';
  model: string | null;
}

export const assistantApi = {
  status: (signal?: AbortSignal) => http.get<AssistantStatus>('/assistant/status', undefined, signal),
  /** Runs one fixed, read-only Salesforce lookup by id (see src/config/crmQuestions.ts). */
  crmQuery: (queryId: string) => http.post<CrmAnswer>('/assistant/crm-query', { queryId }),
  /** Answers a free-text question about the org's data with fixed rules (read-only). null = not a data question. */
  answer: (body: { question: string; context?: string }) => http.post<CrmAnswer | null>('/assistant/answer', body),
};
