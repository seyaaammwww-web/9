import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:animate_do/animate_do.dart';

class LeaderboardTab extends StatefulWidget {
  @override
  _LeaderboardTabState createState() => _LeaderboardTabState();
}

class _LeaderboardTabState extends State<LeaderboardTab> {
  String _searchQuery = "";
  final TextEditingController _searchController = TextEditingController();

  // دالة لحساب مستوى الطالب بناءً على النقاط
  String _getLevel(int points) {
    if (points < 100) return "مبتدئ";
    if (points < 500) return "هاوي";
    if (points < 1500) return "محترف";
    return "خبير";
  }

  @override
  Widget build(BuildContext context) {
    final myId = FirebaseAuth.instance.currentUser?.uid;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final textColor = isDark ? Colors.white : Colors.black87;
    final cardColor = Theme.of(context).cardColor;

    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      appBar: AppBar(
        title: Text("لوحة الشرف", style: TextStyle(color: textColor, fontWeight: FontWeight.bold)),
        centerTitle: true,
        backgroundColor: Colors.transparent,
        elevation: 0,
        automaticallyImplyLeading: false,
      ),
      body: Column(
        children: [
          // 1. شريط البحث
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20.0, vertical: 10),
            child: TextField(
              controller: _searchController,
              onChanged: (value) => setState(() => _searchQuery = value.toLowerCase()),
              style: TextStyle(color: textColor),
              decoration: InputDecoration(
                hintText: "ابحث عن متسابق...",
                hintStyle: TextStyle(color: Colors.grey),
                prefixIcon: Icon(Icons.search, color: Color(0xFF6C63FF)),
                filled: true,
                fillColor: cardColor,
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(15), borderSide: BorderSide.none),
                contentPadding: EdgeInsets.symmetric(vertical: 0, horizontal: 20),
              ),
            ),
          ),

          // 2. قائمة المتصدرين
          Expanded(
            child: StreamBuilder<QuerySnapshot>(
              stream: FirebaseFirestore.instance.collection('users').orderBy('totalPoints', descending: true).snapshots(),
              builder: (context, snapshot) {
                if (!snapshot.hasData) return Center(child: CircularProgressIndicator());
                
                // تصفية النتائج بناءً على البحث
                var filteredDocs = snapshot.data!.docs.where((doc) {
                  var name = (doc['name'] ?? "").toString().toLowerCase();
                  return name.contains(_searchQuery);
                }).toList();

                if (filteredDocs.isEmpty) {
                  return Center(child: Text("لا توجد نتائج مطابقة.", style: TextStyle(color: Colors.grey)));
                }

                return ListView.builder(
                  padding: EdgeInsets.all(20),
                  itemCount: filteredDocs.length,
                  itemBuilder: (ctx, i) {
                    var data = filteredDocs[i];
                    String userId = filteredDocs[i].id;
                    int points = data['totalPoints'] ?? 0;
                    String role = data['role'] ?? 'student';
                    String? photoUrl = data.data().toString().contains('photoUrl') ? data['photoUrl'] : null;
                    bool isCurrentUser = userId == myId;

                    // تحديد الألوان
                    Color? rankColor;
                    if (i == 0 && _searchQuery.isEmpty) rankColor = Colors.amber;
                    else if (i == 1 && _searchQuery.isEmpty) rankColor = Colors.grey[400];
                    else if (i == 2 && _searchQuery.isEmpty) rankColor = Colors.brown[300];
                    else if (isCurrentUser) rankColor = Color(0xFF6C63FF); // لون الطالب الحالي

                    return FadeInUp(
                      delay: Duration(milliseconds: i * 50),
                      child: Container(
                        margin: EdgeInsets.only(bottom: 12),
                        decoration: BoxDecoration(
                          color: cardColor,
                          borderRadius: BorderRadius.circular(15),
                          boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 5)],
                          // حدود خاصة للطالب الحالي ولأصحاب المراكز الأولى
                          border: Border.all(
                            color: isCurrentUser ? Color(0xFF6C63FF) : (rankColor != null ? rankColor : Colors.transparent), 
                            width: isCurrentUser ? 2.5 : (rankColor != null ? 1.5 : 0)
                          ),
                        ),
                        child: ListTile(
                          contentPadding: EdgeInsets.symmetric(horizontal: 20, vertical: 8),
                          leading: Stack(
                            alignment: Alignment.center,
                            children: [
                              CircleAvatar(
                                radius: 22,
                                backgroundColor: rankColor != null ? rankColor.withOpacity(0.2) : Colors.grey.withOpacity(0.1),
                                backgroundImage: photoUrl != null ? NetworkImage(photoUrl) : null,
                                child: photoUrl == null ? Icon(Icons.person, color: Colors.grey) : null,
                              ),
                              // عرض الرتبة فقط إذا كان ضمن المراكز الـ 3 الأولى بدون بحث
                              if (i < 3 && _searchQuery.isEmpty)
                                Positioned(
                                  bottom: 0, right: 0,
                                  child: Icon(Icons.star, color: rankColor, size: 16),
                                )
                            ],
                          ),
                          title: Text(
                            data['name'] ?? 'مستخدم', 
                            style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: textColor)
                          ),
                          subtitle: Text(
                            "${role == 'teacher' ? 'معلم' : _getLevel(points)}", 
                            style: TextStyle(color: Colors.grey, fontSize: 12)
                          ),
                          trailing: Container(
                            padding: EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                            decoration: BoxDecoration(
                              color: Color(0xFF6C63FF).withOpacity(0.1),
                              borderRadius: BorderRadius.circular(20)
                            ),
                            child: Text(
                              "$points XP", 
                              style: TextStyle(fontWeight: FontWeight.bold, color: Color(0xFF6C63FF), fontSize: 12)
                            ),
                          ),
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
    );
  }
}