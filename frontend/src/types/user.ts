/** User preference types. */

/**
 * Per-node configuration stored in fin_users.user_preferences.
 * All keys are optional — absent means "use system default".
 */
export interface NodeConfig {
  /** Pause execution after this node and wait for the user to approve before continuing. */
  human_in_the_loop?: boolean;
  /** Research thoroughness for data-gathering nodes. */
  depth?: 'shallow' | 'normal' | 'deep';
  /** Max agent loop iterations for deep-agent nodes. */
  max_iterations?: number;
  /** LLM sampling temperature (0.0–2.0). */
  temperature?: number;
  /** Output verbosity for synthesis / conclusion nodes. */
  detail_level?: 'brief' | 'standard' | 'detailed';
}

/** Single row from fin_users.user_preferences. */
export interface UserPreference {
  id: number;
  user_id: string;
  node_name: string;
  config: NodeConfig;
  updated_at: string;
}

/** Shape returned by GET /api/v1/users/me/preferences */
export type UserPreferencesResponse = UserPreference[];
