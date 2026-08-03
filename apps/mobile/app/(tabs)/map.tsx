import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import MapView, { Marker } from "react-native-maps";
import { Screen } from "@/components/Screen";
import { api } from "@/lib/api";
import type { Bootstrap } from "@/lib/types";
export default function MapScreen(){const[data,setData]=useState<Bootstrap|null>(null);useEffect(()=>{void api<Bootstrap>("/mobile/bootstrap").then(setData)},[]);const located=(data?.properties??[]).filter(p=>p.latitude&&p.longitude);return <Screen title="Bản đồ"><View style={s.mapWrap}>{located.length?<MapView style={s.map} initialRegion={{latitude:21.0285,longitude:105.8542,latitudeDelta:.2,longitudeDelta:.2}}>{located.map(p=><Marker key={p.id} coordinate={{latitude:Number(p.latitude),longitude:Number(p.longitude)}} title={p.title}/>)}</MapView>:<View style={s.fallback}><Text>Chưa có tọa độ trong dữ liệu demo. Danh sách vẫn hoạt động ngoại tuyến.</Text></View>}</View></Screen>}
const s=StyleSheet.create({mapWrap:{height:520,borderRadius:18,overflow:"hidden"},map:{flex:1},fallback:{flex:1,backgroundColor:"white",padding:20,justifyContent:"center"}});
