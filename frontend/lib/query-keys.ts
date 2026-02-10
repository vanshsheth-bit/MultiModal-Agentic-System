export const queryKeys = {
  auth: {
    user: ['auth', 'user'] as const,
  },
  documents: {
    all: ['documents'] as const,
    list: () => [...queryKeys.documents.all, 'list'] as const,
  },
  queries: {
    all: ['queries'] as const,
    history: (limit?: number) => [...queryKeys.queries.all, 'history', limit] as const,
  },
  admin: {
    all: ['admin'] as const,
    metrics: () => [...queryKeys.admin.all, 'metrics'] as const,
    systemStatus: () => [...queryKeys.admin.all, 'system-status'] as const,
  },
} as const;