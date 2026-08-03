import { useCallback, useState } from "react";
import { useFocusEffect, router } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { Screen } from "@/components/Screen";
import { api } from "@/lib/api";
import type { Bootstrap } from "@/lib/types";
export default function Home(){const[data,setData]=useState<Bootstrap|null>(null);useFocusEffect(useCallback(()=>{void api<Bootstrap>("/mobile/bootstrap").then(setData);return()=>{}},[]));return <Screen title={`Xin chào${data?.user?.full_name?`, ${data.user.full_name}`:""}`}><Text style={s.copy}>Khám phá căn nhà, định giá và tour không gian trên một ứng dụng.</Text>{data?.properties.map((p)=><Pressable key={p.id} style={s.card} onPress={()=>router.push(`/property/${p.slug}`)}><View><Text style={s.title}>{p.title}</Text><Text>{p.district} · {p.has_3d?"Có 3D":"Ảnh"}</Text></View><Text style={s.price}>{new Intl.NumberFormat("vi-VN").format(p.price)} ₫</Text></Pressable>)}</Screen>}
const s=StyleSheet.create({copy:{fontSize:16,color:"#655f55"},card:{backgroundColor:"white",padding:16,borderRadius:16,gap:10},title:{fontSize:17,fontWeight:"700"},price:{fontSize:16,fontWeight:"800",color:"#1d5f4a"}});
