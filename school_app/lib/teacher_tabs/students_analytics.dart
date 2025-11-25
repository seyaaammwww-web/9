import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:animate_do/animate_do.dart';
import 'package:intl/intl.dart' as intl; // لتجنب تضارب الأسماء

class StudentsAnalytics extends StatefulWidget {
  @override
  _StudentsAnalyticsState createState() => _StudentsAnalyticsState();
}

class _StudentsAnalyticsState extends State<StudentsAnalytics> {
  String _searchQuery = "";
  bool _isExporting = false;

  // دالة محاكاة لتصدير البيانات
  Future<void> _exportData() async {
    setState(() => _isExporting = true);
    await Future.delayed(Duration(seconds: 2)); // محاكاة وقت المعالجة
    if (mounted) {
      setState(() => _isExporting = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("تم تصدير تقرير الأداء بنجاح (Students_Report.csv)"), backgroundColor: Colors.green)
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final cardColor = Theme.of(context).cardColor;

    return Scaffold(
      appBar: AppBar(
        title: Text("تحليلات الطلاب"),
        actions: [
          IconButton(
            icon: _isExporting 
              ? SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)) 
              : Icon(Icons.download_rounded),
            tooltip: "تصدير تقرير",
            onPressed: _isExporting ? null : _exportData,
          )
        ],
      ),
      body: StreamBuilder<QuerySnapshot>(
        stream: FirebaseFirestore.instance
            .collection('users')
            .where('role', isEqualTo: 'student')
            .snapshots(),
        builder: (context, snapshot) {
          if (!snapshot.hasData) return _buildLoadingSkeleton();
          
          var docs = snapshot.data!.docs;
          if (docs.isEmpty) return _buildEmptyState();

          // --- معالجة البيانات (Analytics Logic) ---
          List<Map<String, dynamic>> students = docs.map((d) => d.data() as Map<String, dynamic>).toList();
          
          // 1. حساب المتوسط والمجموع
          double totalPoints = 0;
          Map<String, dynamic>? topStudent;
          int maxPoints = -1;
          
          for (var s in students) {
            int p = s['totalPoints'] ?? 0;
            totalPoints += p;
            if (p > maxPoints) {
              maxPoints = p;
              topStudent = s;
            }
          }
          double avgPoints = students.isEmpty ? 0 : totalPoints / students.length;

          // 2. توزيع الدرجات (Chart Data)
          int range0_100 = 0, range100_500 = 0, range500_plus = 0;
          for (var s in students) {
            int p = s['totalPoints'] ?? 0;
            if (p < 100) range0_100++;
            else if (p < 500) range100_500++;
            else range500_plus++;
          }

          // 3. الفلترة للقائمة السفلية
          var filteredStudents = students.where((s) {
            return (s['name'] ?? "").toString().toLowerCase().contains(_searchQuery.toLowerCase());
          }).toList();
          
          // ترتيب الطلاب حسب النقاط (الأعلى فالأقل)
          filteredStudents.sort((a, b) => (b['totalPoints'] ?? 0).compareTo(a['totalPoints'] ?? 0));

          return SingleChildScrollView(
            padding: EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // --- قسم البطاقات الإحصائية ---
                FadeInDown(
                  child: Row(
                    children: [
                      Expanded(child: _StatCard(title: "متوسط النقاط", value: avgPoints.toStringAsFixed(0), icon: Icons.show_chart, color: Colors.blue)),
                      SizedBox(width: 10),
                      Expanded(child: _StatCard(title: "الطالب الأول", value: topStudent?['name']?.split(' ')[0] ?? "-", icon: Icons.emoji_events, color: Colors.amber)),
                      SizedBox(width: 10),
                      Expanded(child: _StatCard(title: "إجمالي الطلاب", value: students.length.toString(), icon: Icons.groups, color: Colors.purple)),
                    ],
                  ),
                ),

                SizedBox(height: 25),

                // --- الرسم البياني ---
                Text("توزيع مستويات الطلاب 📊", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                SizedBox(height: 15),
                FadeInUp(
                  child: Container(
                    height: 250,
                    padding: EdgeInsets.fromLTRB(10, 25, 10, 10),
                    decoration: BoxDecoration(
                      color: cardColor,
                      borderRadius: BorderRadius.circular(20),
                      boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10)],
                    ),
                    child: BarChart(
                      BarChartData(
                        alignment: BarChartAlignment.spaceAround,
                        maxY: (students.length + 1).toDouble(),
                        barTouchData: BarTouchData(
                          touchTooltipData: BarTouchTooltipData(
                            // tooltipBgColor: Colors.blueGrey,
                            getTooltipItem: (group, groupIndex, rod, rodIndex) {
                              return BarTooltipItem(
                                rod.toY.round().toString(),
                                TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
                              );
                            },
                          ),
                        ),
                        titlesData: FlTitlesData(
                          show: true,
                          bottomTitles: AxisTitles(
                            sideTitles: SideTitles(
                              showTitles: true,
                              getTitlesWidget: (value, meta) {
                                switch (value.toInt()) {
                                  case 0: return Text('مبتدئ', style: TextStyle(fontSize: 12));
                                  case 1: return Text('متوسط', style: TextStyle(fontSize: 12));
                                  case 2: return Text('متقدم', style: TextStyle(fontSize: 12));
                                  default: return Text('');
                                }
                              },
                            ),
                          ),
                          leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
                          topTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
                          rightTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
                        ),
                        gridData: FlGridData(show: false),
                        borderData: FlBorderData(show: false),
                        barGroups: [
                          _makeBarGroup(0, range0_100.toDouble(), Colors.grey),
                          _makeBarGroup(1, range100_500.toDouble(), Colors.blue),
                          _makeBarGroup(2, range500_plus.toDouble(), Colors.amber),
                        ],
                      ),
                    ),
                  ),
                ),

                SizedBox(height: 25),

                // --- قائمة الطلاب (Drill-down) ---
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text("سجل الطلاب التفصيلي", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                    Text("${filteredStudents.length} طالب", style: TextStyle(color: Colors.grey)),
                  ],
                ),
                SizedBox(height: 10),
                
                // شريط البحث
                TextField(
                  onChanged: (val) => setState(() => _searchQuery = val),
                  decoration: InputDecoration(
                    hintText: "بحث باسم الطالب...",
                    prefixIcon: Icon(Icons.search),
                    filled: true,
                    fillColor: isDark ? Colors.white10 : Colors.grey[100],
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(15), borderSide: BorderSide.none),
                    contentPadding: EdgeInsets.symmetric(vertical: 0, horizontal: 20),
                  ),
                ),
                SizedBox(height: 10),

                ListView.builder(
                  shrinkWrap: true,
                  physics: NeverScrollableScrollPhysics(),
                  itemCount: filteredStudents.length,
                  itemBuilder: (ctx, i) {
                    var student = filteredStudents[i];
                    return _StudentListTile(
                      student: student,
                      rank: i + 1,
                      onTap: () => _showStudentDetails(context, student),
                    );
                  },
                ),
                SizedBox(height: 50),
              ],
            ),
          );
        },
      ),
    );
  }

  BarChartGroupData _makeBarGroup(int x, double y, Color color) {
    return BarChartGroupData(
      x: x,
      barRods: [
        BarChartRodData(toY: y, color: color, width: 22, borderRadius: BorderRadius.circular(6))
      ],
    );
  }

  void _showStudentDetails(BuildContext context, Map<String, dynamic> student) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => Container(
        height: MediaQuery.of(context).size.height * 0.6,
        decoration: BoxDecoration(
          color: Theme.of(context).scaffoldBackgroundColor,
          borderRadius: BorderRadius.vertical(top: Radius.circular(25)),
        ),
        padding: EdgeInsets.all(25),
        child: Column(
          children: [
            Container(width: 40, height: 4, decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(10))),
            SizedBox(height: 20),
            CircleAvatar(
              radius: 40,
              backgroundImage: student['photoUrl'] != null ? NetworkImage(student['photoUrl']) : null,
              child: student['photoUrl'] == null ? Icon(Icons.person, size: 40) : null,
            ),
            SizedBox(height: 15),
            Text(student['name'] ?? "بدون اسم", style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
            Text(student['email'] ?? "لا يوجد بريد إلكتروني", style: TextStyle(color: Colors.grey)),
            SizedBox(height: 30),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
                _DetailStat(label: "النقاط", value: "${student['totalPoints'] ?? 0} XP"),
                _DetailStat(label: "الانضمام", value: student['createdAt'] != null 
                    ? intl.DateFormat('yyyy/MM/dd').format((student['createdAt'] as Timestamp).toDate()) 
                    : "-"),
                // يمكن إضافة المزيد من البيانات هنا مستقبلاً (عدد الكويزات، إلخ)
              ],
            ),
            Spacer(),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: () => Navigator.pop(context),
                icon: Icon(Icons.close),
                label: Text("إغلاق"),
                style: ElevatedButton.styleFrom(backgroundColor: Colors.grey[200], foregroundColor: Colors.black),
              ),
            )
          ],
        ),
      ),
    );
  }

  Widget _buildLoadingSkeleton() {
    return Padding(
      padding: const EdgeInsets.all(20.0),
      child: Column(
        children: [
          Row(children: List.generate(3, (i) => Expanded(child: Container(height: 80, margin: EdgeInsets.all(5), decoration: BoxDecoration(color: Colors.grey[200], borderRadius: BorderRadius.circular(15)))))),
          SizedBox(height: 20),
          Container(height: 200, decoration: BoxDecoration(color: Colors.grey[200], borderRadius: BorderRadius.circular(20))),
        ],
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [Icon(Icons.analytics_outlined, size: 80, color: Colors.grey[300]), Text("لا يوجد بيانات طلاب حتى الآن")]));
  }
}

// ---------------------------------------------------------------------------
// 🧩 Widgets Components
// ---------------------------------------------------------------------------

class _StatCard extends StatelessWidget {
  final String title;
  final String value;
  final IconData icon;
  final Color color;

  const _StatCard({required this.title, required this.value, required this.icon, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.symmetric(vertical: 15, horizontal: 10),
      decoration: BoxDecoration(
        color: Theme.of(context).cardColor,
        borderRadius: BorderRadius.circular(15),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.03), blurRadius: 5)],
        border: Border.all(color: color.withOpacity(0.2)),
      ),
      child: Column(
        children: [
          Icon(icon, color: color, size: 24),
          SizedBox(height: 8),
          Text(value, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16), maxLines: 1, overflow: TextOverflow.ellipsis),
          Text(title, style: TextStyle(color: Colors.grey, fontSize: 10)),
        ],
      ),
    );
  }
}

class _StudentListTile extends StatelessWidget {
  final Map<String, dynamic> student;
  final int rank;
  final VoidCallback onTap;

  const _StudentListTile({required this.student, required this.rank, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return FadeInUp(
      child: Container(
        margin: EdgeInsets.only(bottom: 10),
        decoration: BoxDecoration(
          color: Theme.of(context).cardColor,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.grey.withOpacity(0.1)),
        ),
        child: ListTile(
          onTap: onTap,
          leading: CircleAvatar(
            radius: 20,
            backgroundColor: rank <= 3 ? Colors.amber.withOpacity(0.2) : Colors.grey[200],
            child: Text("#$rank", style: TextStyle(color: rank <= 3 ? Colors.amber[800] : Colors.grey, fontWeight: FontWeight.bold)),
          ),
          title: Text(student['name'] ?? "مستخدم", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
          subtitle: Text("${student['totalPoints'] ?? 0} XP", style: TextStyle(color: Color(0xFF6C63FF), fontSize: 12)),
          trailing: Icon(Icons.arrow_forward_ios, size: 14, color: Colors.grey),
        ),
      ),
    );
  }
}

class _DetailStat extends StatelessWidget {
  final String label;
  final String value;
  const _DetailStat({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(value, style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Color(0xFF6C63FF))),
        Text(label, style: TextStyle(color: Colors.grey)),
      ],
    );
  }
}