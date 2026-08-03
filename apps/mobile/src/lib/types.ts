export type MobileUser = { id: string; email?: string; full_name: string; role: string };
export type MobileSession = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user?: MobileUser;
};
export type Organization = { id: string; name: string; slug: string; role: string };
export type PropertyItem = {
  id: string;
  organization_id?: string | null;
  slug: string;
  title: string;
  price: number;
  district: string;
  property_type?: string | null;
  has_3d: boolean;
  latitude?: number | null;
  longitude?: number | null;
};
export type Bootstrap = {
  user: MobileUser;
  organizations: Organization[];
  properties: PropertyItem[];
  deep_links: string[];
};
export type OfflineMutation = {
  client_mutation_id: string;
  mutation_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};
