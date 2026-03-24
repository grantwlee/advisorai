import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiService {
  final String baseUrl;
  final int timeoutSeconds;

  ApiService({
    this.baseUrl = '',
    this.timeoutSeconds = 240,
  });

  String _buildUrl(String endpoint) {
    final cleanEndpoint =
        endpoint.startsWith('/') ? endpoint.substring(1) : endpoint;
    return '$baseUrl/$cleanEndpoint';
  }

  Future<dynamic> get(String endpoint) async {
    final url = Uri.parse(_buildUrl(endpoint));
    try {
      final response = await http.get(url).timeout(
        Duration(seconds: timeoutSeconds),
        onTimeout: () =>
            throw Exception('Request timeout after $timeoutSeconds seconds'),
      );

      if (response.statusCode == 200) {
        return jsonDecode(response.body);
      }
      throw Exception(
        'HTTP ${response.statusCode}: ${response.reasonPhrase}\n${response.body}',
      );
    } catch (e) {
      throw Exception('API request failed: $e');
    }
  }

  Future<Map<String, dynamic>> post(
    String endpoint,
    Map<String, dynamic> data,
  ) async {
    final url = Uri.parse(_buildUrl(endpoint));
    try {
      final response = await http
          .post(
            url,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(data),
          )
          .timeout(
            Duration(seconds: timeoutSeconds),
            onTimeout: () =>
                throw Exception('Request timeout after $timeoutSeconds seconds'),
          );

      if (response.statusCode == 200 || response.statusCode == 201) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }
      throw Exception(
        'HTTP ${response.statusCode}: ${response.reasonPhrase}\n${response.body}',
      );
    } catch (e) {
      throw Exception('API request failed: $e');
    }
  }

  Future<void> delete(String endpoint) async {
    final url = Uri.parse(_buildUrl(endpoint));
    try {
      final response = await http.delete(url).timeout(
        Duration(seconds: timeoutSeconds),
        onTimeout: () =>
            throw Exception('Request timeout after $timeoutSeconds seconds'),
      );
      if (response.statusCode != 200) {
        throw Exception(
          'HTTP ${response.statusCode}: ${response.reasonPhrase}\n${response.body}',
        );
      }
    } catch (e) {
      throw Exception('API request failed: $e');
    }
  }

  Future<Map<String, dynamic>> getHealth() async {
    return await get('/api/health');
  }

  Future<List<Map<String, dynamic>>> getCourses() async {
    final data = await get('/api/courses');
    if (data is List) {
      return data.cast<Map<String, dynamic>>();
    }
    throw Exception('Unexpected response type for courses');
  }

  Future<List<Map<String, dynamic>>> searchStudents(String query) async {
    final data = await get('/api/students/search?q=${Uri.encodeComponent(query)}');
    if (data is List) {
      return data.cast<Map<String, dynamic>>();
    }
    throw Exception('Unexpected response type for search');
  }

  Future<Map<String, dynamic>> getStudentDetail(String studentId) async {
    return await get('/api/students/$studentId');
  }

  Future<List<Map<String, dynamic>>> getStudentCourses(String studentId) async {
    final data = await get('/api/students/$studentId/courses');
    if (data is List) {
      return data.cast<Map<String, dynamic>>();
    }
    throw Exception('Unexpected response type for student courses');
  }

  Future<Map<String, dynamic>> addStudentCourse({
    required String studentId,
    required String courseCode,
    required String status,
    String? title,
    int? credits,
    String? term,
    String? grade,
  }) async {
    return await post('/api/students/$studentId/courses', {
      'course_code': courseCode,
      'status': status,
      if (title != null && title.isNotEmpty) 'title': title,
      if (credits != null) 'credits': credits,
      if (term != null && term.isNotEmpty) 'term': term,
      if (grade != null && grade.isNotEmpty) 'grade': grade,
    });
  }

  Future<void> deleteStudentCourse(String studentId, int recordId) async {
    await delete('/api/students/$studentId/courses/$recordId');
  }

  Future<Map<String, dynamic>> queryAdvisor({
    required String question,
    String? studentId,
    int topK = 5,
  }) async {
    return await post('/api/query', {
      'question': question,
      if (studentId != null && studentId.isNotEmpty) 'student_id': studentId,
      'top_k': topK,
    });
  }

  Future<Map<String, dynamic>> sendChatMessage(
    String message, {
    String? studentId,
  }) async {
    return await queryAdvisor(question: message, studentId: studentId);
  }
}
