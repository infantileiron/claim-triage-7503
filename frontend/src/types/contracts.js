/** @typedef {{id:number,code:string,amount:number,distance:number,holiday:boolean,label:0|1|null,note:string}} Claim */
/** @typedef {{id:number,name:string,threshold:number,state:string,result:object}} Training */
/** @typedef {{id:number,claim_id:number,training_id:number,score:number,decision:string,status:string}} Review */
/** @typedef {{id:number,request_id:string,training_id:number,holiday:string,epsilon:number,actor:string,state:string,charged:number,refunded:number,result:object|null,error:string,created:string}} DpRequest */
/** @typedef {{training_id:number,total:number,spent:number,remaining:number}} PrivacyLedger */
