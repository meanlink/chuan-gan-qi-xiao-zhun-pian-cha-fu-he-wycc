/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{target:number,completed:number,percent:number,segment_size:number,bands:Array<{band:string,n:number,completed:number}>}} JobProgress */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean,parent_id:number|null,superseded_by:number|null,progress:JobProgress}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
export {};
