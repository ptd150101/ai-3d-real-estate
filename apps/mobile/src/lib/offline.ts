import AsyncStorage from "@react-native-async-storage/async-storage";
import { api } from "./api";
import { getDeviceId } from "./device";
import type { OfflineMutation } from "./types";
const KEY="nestora.offline-mutations";
async function read():Promise<OfflineMutation[]>{const raw=await AsyncStorage.getItem(KEY);return raw?JSON.parse(raw):[]}
async function write(items:OfflineMutation[]){await AsyncStorage.setItem(KEY,JSON.stringify(items))}
export async function enqueue(mutation_type:string,payload:Record<string,unknown>){const items=await read();items.push({client_mutation_id:`${Date.now()}-${Math.random().toString(36).slice(2)}`,mutation_type,payload,created_at:new Date().toISOString()});await write(items)}
export async function flushQueue():Promise<number>{const items=await read();const remaining:OfflineMutation[]=[];let count=0;for(const item of items){try{await api("/mobile/mutations",{method:"POST",body:JSON.stringify({...item,device_id:await getDeviceId()})});count++}catch{remaining.push(item)}}await write(remaining);return count}
export async function queueSize():Promise<number>{return (await read()).length}
