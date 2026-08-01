import type { PropsWithChildren } from "react";
import { SafeAreaView, ScrollView, StyleSheet, Text, View } from "react-native";
export function Screen({title,children}:{title:string}&PropsWithChildren){return <SafeAreaView style={s.safe}><ScrollView contentContainerStyle={s.body}><View><Text style={s.eyebrow}>NESTORA · P2</Text><Text style={s.title}>{title}</Text></View>{children}</ScrollView></SafeAreaView>}
const s=StyleSheet.create({safe:{flex:1,backgroundColor:"#f6f4ee"},body:{padding:20,gap:16},eyebrow:{fontSize:12,fontWeight:"700",letterSpacing:1.4,color:"#6e6555"},title:{fontSize:28,fontWeight:"800",color:"#181714",marginTop:4}});
