import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Device from "expo-device";
import { Platform } from "react-native";

const KEY = "nestora.device-id";
export async function getDeviceId(): Promise<string> {
  const existing = await AsyncStorage.getItem(KEY);
  if (existing) return existing;
  const id = `${Platform.OS}-${Device.modelName ?? "device"}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  await AsyncStorage.setItem(KEY, id);
  return id;
}
