import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { api } from "./api";
import { getDeviceId } from "./device";

export async function registerPush(): Promise<string | null> {
  if (!Device.isDevice) return null;
  if (Platform.OS === "android") await Notifications.setNotificationChannelAsync("general", {name:"General",importance:Notifications.AndroidImportance.DEFAULT});
  const current=await Notifications.getPermissionsAsync();
  const permission=current.status==="granted"?current:await Notifications.requestPermissionsAsync();
  if(permission.status!=="granted")return null;
  const projectId=Constants.expoConfig?.extra?.eas?.projectId as string|undefined;
  if(!projectId || projectId.startsWith("00000000")) return null;
  const token=(await Notifications.getExpoPushTokenAsync({projectId})).data;
  await api("/mobile/devices",{method:"POST",body:JSON.stringify({device_id:await getDeviceId(),platform:Platform.OS,push_token:token,app_version:Constants.expoConfig?.version})});
  return token;
}
