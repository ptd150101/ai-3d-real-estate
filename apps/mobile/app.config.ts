import type { ConfigContext, ExpoConfig } from "expo/config";

const base = require("./app.json").expo as ExpoConfig;

export default ({ config }: ConfigContext): ExpoConfig => {
  const projectId = process.env.EAS_PROJECT_ID;
  const apiUrl = process.env.EXPO_PUBLIC_API_URL || String(base.extra?.apiUrl || "");
  return {
    ...config,
    ...base,
    extra: {
      ...base.extra,
      apiUrl,
      ...(projectId ? { eas: { projectId } } : {}),
    },
    ...(projectId
      ? { updates: { url: `https://u.expo.dev/${projectId}`, fallbackToCacheTimeout: 0 } }
      : {}),
  };
};
