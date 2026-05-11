/** Auth-related types. */

/** Response from the guest / OAuth login endpoints. */
export interface GuestAuthResponse {
  id: string;
  username: string;
  display_name?: string;
  email?: string;
  email_verified: boolean;
  avatar_url?: string;
  auth_type: string;
  is_new: boolean;
}

/** Centrifugo token bundle returned by the token-grant endpoint. */
export interface CentrifugoTokenResponse {
  ws_url: string;
  connection_token: string;
  subscription_token: string;
  shard_index: number;
  channel: string;
}
