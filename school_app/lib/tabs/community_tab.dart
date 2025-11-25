import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:animate_do/animate_do.dart';
import '../private_chat_screen.dart';

class CommunityTab extends StatefulWidget {
  @override
  _CommunityTabState createState() => _CommunityTabState();
}

class _CommunityTabState extends State<CommunityTab> {
  String _searchQuery = "";
  final TextEditingController _searchController = TextEditingController();

  @override
  Widget build(BuildContext context) {
    final myId = FirebaseAuth.instance.currentUser?.uid;
    // متغيرات الثيم للوضع الليلي/النهاري
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final textColor = isDark ? Colors.white : Colors.black87;
    final cardColor = Theme.of(context).cardColor;

    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      body: Padding(
        padding: EdgeInsets.fromLTRB(20, 50, 20, 0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 1. العنوان
            FadeInDown(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text("مجتمع المبرمجين", style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold, color: Color(0xFF6C63FF))),
                  Text("تواصل مع زملائك وتبادل الخبرات", style: TextStyle(color: Colors.grey)),
                ],
              ),
            ),
            
            SizedBox(height: 20),

            // 2. شريط البحث (الميزة الجديدة)
            FadeInDown(
              delay: Duration(milliseconds: 200),
              child: TextField(
                controller: _searchController,
                onChanged: (value) {
                  setState(() {
                    _searchQuery = value.toLowerCase();
                  });
                },
                style: TextStyle(color: textColor),
                decoration: InputDecoration(
                  hintText: "ابحث عن صديق أو معلم...",
                  hintStyle: TextStyle(color: Colors.grey),
                  prefixIcon: Icon(Icons.search, color: Color(0xFF6C63FF)),
                  filled: true,
                  fillColor: cardColor,
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(15), borderSide: BorderSide.none),
                  contentPadding: EdgeInsets.symmetric(vertical: 0, horizontal: 20),
                ),
              ),
            ),

            SizedBox(height: 15),

            // 3. قائمة المستخدمين
            Expanded(
              child: StreamBuilder<QuerySnapshot>(
                stream: FirebaseFirestore.instance.collection('users').where(FieldPath.documentId, isNotEqualTo: myId).snapshots(),
                builder: (context, snapshot) {
                  if (!snapshot.hasData) return Center(child: CircularProgressIndicator());
                  
                  // تصفية النتائج بناءً على البحث
                  var docs = snapshot.data!.docs.where((doc) {
                    var name = (doc['name'] ?? "").toString().toLowerCase();
                    return name.contains(_searchQuery);
                  }).toList();

                  if (docs.isEmpty) {
                    return Center(child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                      Icon(Icons.person_search_rounded, size: 60, color: Colors.grey[300]),
                      SizedBox(height: 10),
                      Text("لا توجد نتائج مطابقة", style: TextStyle(color: Colors.grey)),
                    ]));
                  }

                  return ListView.builder(
                    padding: EdgeInsets.only(bottom: 100),
                    itemCount: docs.length,
                    itemBuilder: (ctx, i) {
                      var user = docs[i];
                      String role = (user.data() as Map).containsKey('role') ? user['role'] : 'student';
                      String name = user['name'] ?? 'مستخدم';
                      String? photoUrl = user.data().toString().contains('photoUrl') ? user['photoUrl'] : null;
                      bool isTeacher = role == 'teacher';

                      return FadeInUp(
                        delay: Duration(milliseconds: i * 50),
                        child: Container(
                          margin: EdgeInsets.only(bottom: 12),
                          decoration: BoxDecoration(
                            color: cardColor,
                            borderRadius: BorderRadius.circular(15),
                            boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.03), blurRadius: 10)],
                            border: isTeacher ? Border.all(color: Colors.orange.withOpacity(0.3), width: 1) : null // تمييز المعلم بحدود خفيفة
                          ),
                          child: ListTile(
                            contentPadding: EdgeInsets.all(10),
                            leading: Stack(
                              children: [
                                CircleAvatar(
                                  radius: 28,
                                  backgroundColor: isTeacher ? Colors.orange.withOpacity(0.1) : Colors.indigo.withOpacity(0.1),
                                  backgroundImage: photoUrl != null ? NetworkImage(photoUrl) : null,
                                  child: photoUrl == null ? Icon(isTeacher ? Icons.school : Icons.person, color: isTeacher ? Colors.orange : Colors.indigo) : null,
                                ),
                                // نقطة الحالة (Online Status) - محاكاة
                                Positioned(
                                  bottom: 0, right: 0,
                                  child: Container(
                                    width: 14, height: 14,
                                    decoration: BoxDecoration(
                                      color: Colors.greenAccent,
                                      shape: BoxShape.circle,
                                      border: Border.all(color: cardColor, width: 2)
                                    ),
                                  ),
                                )
                              ],
                            ),
                            title: Row(
                              children: [
                                Text(name, style: TextStyle(fontWeight: FontWeight.bold, color: textColor)),
                                if (isTeacher) ...[
                                  SizedBox(width: 5),
                                  Icon(Icons.verified, size: 16, color: Colors.orange) // شارة التوثيق للمعلم
                                ]
                              ],
                            ),
                            subtitle: Text(
                              isTeacher ? 'معلم ومشرف' : 'طالب مجتهد', 
                              style: TextStyle(color: isTeacher ? Colors.orange[700] : Colors.grey[600], fontSize: 12, fontWeight: isTeacher ? FontWeight.bold : FontWeight.normal)
                            ),
                            trailing: Container(
                              padding: EdgeInsets.all(8),
                              decoration: BoxDecoration(color: Color(0xFF6C63FF).withOpacity(0.1), shape: BoxShape.circle),
                              child: Icon(Icons.chat_bubble_outline, color: Color(0xFF6C63FF), size: 20),
                            ),
                            onTap: () {
                              Navigator.push(context, MaterialPageRoute(
                                builder: (_) => PrivateChatScreen(
                                  targetUserIds: user.id,
                                  targetUserName: name,
                                  targetUserImage: photoUrl,
                                )
                              ));
                            },
                          ),
                        ),
                      );
                    },
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}