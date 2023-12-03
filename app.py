from flask import Flask, jsonify, request
from neo4j import GraphDatabase
from dotenv import load_dotenv
import os 

app = Flask(__name__)
driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "test1234"),database="neo4j")

def get_employees(tx, sort_by=None, filter_by=None):
    query = "MATCH (employee:Employee)-[:WORKS_IN]->(department) RETURN employee.name AS name, employee.surname AS surname, department.name AS department"

    if sort_by:
        query += f" ORDER BY employee.{sort_by}"

    results = tx.run(query).data()
    employees = [{'name': result['name'], 'surname': result['surname'], 'department': result['department']} for result in results]
    return employees

@app.route('/employees', methods=['GET'])
def get_employees_route():
    sort_by = request.args.get('sort_by')

    with driver.session() as session:
        employees = session.read_transaction(get_employees, sort_by)

    response = {'employees': employees}
    return jsonify(response)



def add_employee(tx, name, surname, department):
    query = (
        "CREATE (e:Employee {name: $name, surname: $surname}) "
        "WITH e "
        "MATCH (d:Department {name: $department}) "
        "CREATE (e)-[:WORKS_IN]->(d)"
    )
    tx.run(query, name=name, surname=surname, department=department)

@app.route('/employees', methods=['POST'])
def add_employee_route():
    data = request.get_json()
    required_fields = ['name', 'surname', 'department']

    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400

    name = data['name']
    surname = data['surname']
    department = data['department']

    with driver.session() as session:
        session.write_transaction(add_employee, name, surname, department)

    return jsonify({'status': 'success'}), 201



def update_employee(tx, name, new_name, surname, department):
    query = (
        "MATCH (employee:Employee {name: $name}) "
        "SET employee.name = $new_name, employee.surname = $surname "
        "WITH employee "
        "MATCH (department:Department {name: $department}) "
        "MERGE (employee)-[:WORKS_IN]->(department) "
        "RETURN employee.name AS name, employee.surname AS surname, department.name AS department"
    )
    result = tx.run(query, name=name, new_name=new_name, surname=surname, department=department)
    updated_employee = result.single()
    return updated_employee

@app.route('/employees/<string:name>', methods=['PUT'])
def update_employee_route(name):
    data = request.get_json()
    new_name = data.get('name')
    surname = data.get('surname')
    department = data.get('department')

    with driver.session() as session:
        updated_employee = session.write_transaction(update_employee, name, new_name, surname, department)

    if not updated_employee:
        response = {'message': 'Employee not found'}
        return jsonify(response), 404
    else:
        return jsonify({
            'name': updated_employee['name'],
            'surname': updated_employee['surname'],
            'department': updated_employee['department']
        }), 200



def delete_employee_by_name(tx, name):
    query_check_employee = "MATCH (employee:Employee {name: $name}) RETURN employee"
    employee = tx.run(query_check_employee, name=name).single()

    if not employee:
        return {'message': f"Employee '{name}' not found"}, 404

    query_check_manager = (
        "MATCH (employee:Employee)-[:MANAGES]->(department:Department) "
        "WHERE employee.name = $name "
        "RETURN department, employee"
    )
    department = tx.run(query_check_manager, name=name).single()

    if department:
        department_node = department['department']
        employee_node = department['employee']

        new_manager_query = (
            "MATCH (employee:Employee)-[:WORKS_IN]->(department:Department {name: $department_name}) "
            "WHERE employee.name <> $name "
            "RETURN employee"
        )
        new_manager = tx.run(new_manager_query, department_name=department_node['name'], name=name).single()

        if new_manager:
            new_manager_node = new_manager['employee']

            tx.run("MATCH (employee)-[r:MANAGES]->(department) WHERE employee = $old_manager_node DELETE r",
                old_manager_node=employee_node)
            tx.run("MATCH (new_manager:Employee), (department:Department {name: $department_name}) "
                "WHERE new_manager = $new_manager_node "
                "CREATE (new_manager)-[:MANAGES]->(department)",
                new_manager_node=new_manager_node, department_name=department_node['name'])
        else:
            tx.run("MATCH (employee)-[r:MANAGES]->(department) WHERE employee = $employee_node DELETE r",
                employee_node=employee_node)
            tx.run("MATCH (employee:Employee)-[r:WORKS_IN]->(department:Department) WHERE employee = $employee_node "
                "DELETE r",
                employee_node=employee_node)
            tx.run("DETACH DELETE department", department=department_node)

    tx.run("MATCH (employee:Employee) WHERE employee.name = $name DETACH DELETE employee", name=name)
    return {'message': f"Employee '{name}' deleted successfully"}

@app.route('/employees/<string:name>', methods=['DELETE'])
def delete_employee_by_name_route(name):
    with driver.session() as session:
        session.write_transaction(delete_employee_by_name, name)
        return jsonify({'message': f"Employee '{name}' deleted successfully"}), 200

def get_subordinates_by_name(tx, name):
    query = (
        "MATCH (manager:Employee {name: $name})-[:MANAGES]->(subordinate:Employee) "
        "RETURN subordinate.name AS name, subordinate.surname AS surname"
    )
    result = tx.run(query, name=name)
    subordinates = [{'name': record['name'], 'surname': record['surname']} for record in result]
    return subordinates

def get_subordinates_by_name(tx, name):
    query = (
        "MATCH (manager:Employee {name: $name})-[:MANAGES]->(subordinate:Employee) "
        "RETURN subordinate.name AS name, subordinate.surname AS surname"
    )
    result = tx.run(query, name=name)
    subordinates = [{'name': record['name'], 'surname': record['surname']} for record in result]
    return subordinates

@app.route('/employees/<string:name>/subordinates', methods=['GET'])
def get_subordinates_route(name):
    with driver.session() as session:
        subordinates = session.read_transaction(get_subordinates_by_name, name)

    return jsonify({'subordinates': subordinates}), 200

def get_employee_department(tx, name):
    query = (
        "MATCH (employee:Employee {name: $name}) "
        "OPTIONAL MATCH (employee)-[:WORKS_IN]->(department:Department) "
        "WITH department "
        "OPTIONAL MATCH (department)<-[:WORKS_IN]-(subordinate:Employee) "
        "RETURN department.name AS departmentName, COUNT(subordinate) AS numberOfEmployees"
    )
    result = tx.run(query, name=name).single()
    return result

@app.route('/employees/<string:name>/department', methods=['GET'])
def get_employee_department_route(name):
    with driver.session() as session:
        department_info = session.read_transaction(get_employee_department, name)

    response_data = {
        'department': {
            'name': department_info['departmentName'],
            'numberOfEmployees': department_info['numberOfEmployees']
        }
    }
    return jsonify(response_data), 200


from flask import request

def get_departments(tx, order_by, order_dir):
    query = (
        "MATCH (department:Department) "
        "OPTIONAL MATCH (department)<-[:WORKS_IN]-(employee:Employee) "
        "RETURN department.name AS name, COUNT(employee) AS numberOfEmployees "
        "ORDER BY " + order_by + " " + order_dir
    )
    result = tx.run(query).data()
    return result

@app.route('/departments', methods=['GET'])
def get_departments_route():
    order_by = request.args.get('orderBy', 'name') 
    order_dir = request.args.get('orderDir', 'ASC')

    if order_dir.upper() not in ['ASC', 'DESC']:
        return jsonify({'error': 'Invalid order direction'}), 400

    with driver.session() as session:
        departments = session.read_transaction(get_departments, order_by, order_dir)

    return jsonify({'departments': departments}), 200

async def get_department_employees(tx, department_name):
    query = (
        "MATCH (employee:Employee)-[:WORKS_IN]->(department:Department {name: $department_name}) "
        "RETURN employee.name AS name, employee.surname AS surname"
    )
    result = await tx.run_async(query, department_name=department_name)
    department_employees = [{'name': record['name'], 'surname': record['surname']} for record in result.records()]
    return department_employees


def get_employees_in_department(tx, department_name):
    query = (
        "MATCH (department:Department {name: $department_name})<-[:WORKS_IN]-(employee:Employee) "
        "RETURN employee.name AS name, employee.surname AS surname"
    )
    result = tx.run(query, department_name=department_name).data()
    return result

@app.route('/departments/<string:department_name>/employees', methods=['GET'])
def get_employees_in_department_route(department_name):
    with driver.session() as session:
        employees = session.read_transaction(get_employees_in_department, department_name)

    return jsonify({'employees': employees}), 200


if __name__ == '__main__':
    app.run()

